#!/Users/simoncook/opt/anaconda3/envs/Spectator/bin/python
# -*- coding: utf-8 -*-
"""
Created on Tue Jan 19 23:51:13 2021

@author: simoncook
"""

import datetime as dt
import pandas as pd
import os

from github import Github
from datawrapper import Datawrapper
from uk_covid19 import Cov19API

import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
import numpy as np
from urllib.request import urlopen
from lxml import etree

g = Github(GITHUB_KEY)
repo = g.get_user().get_repo("DataHub")

dw = Datawrapper(access_token = DATAWRAPPER_ACCESS_TOKEN)

#Gmail variables
port = 465  # For SSL
password = GMAIL_PASSWORD
sender_email = sender_email
receiver_email = receiver_email

def gmail_sender(program_name, function_list, workedornot_list):
    
    time = dt.datetime.now().time().replace(microsecond=0)
    
    message = MIMEMultipart("alternative")
    message["Subject"] = "Spectator "+ program_name + f" updated at {time}"
    message["From"] = sender_email
    message["To"] = receiver_email
    
    #expand list
    worked_str = ""
    for i in range(len(function_list)):
        if workedornot_list[i]:
            worked = "all OK"
        else:
            worked = "did not work correctly"
            
        worked_str = worked_str + function_list[i] + ": " + worked + "\r"
    
    text = f"""
       Python has updated your data as follows: \n
        {worked_str}
        """
    message_text = MIMEText(text, "plain")
    message.attach(message_text)

    # Create a secure SSL context
    context = ssl.create_default_context()

    with smtplib.SMTP_SSL("smtp.gmail.com", port, context=context) as server:
        server.login(sender_email, password)
        server.sendmail(sender_email, receiver_email, message.as_string())

    return

def upload_to_github(df, filename):

# =============================================================================
#   creates csv file and upload it to Github repositary
# =============================================================================

    csv_data = df.to_csv()
    dt_string = dt.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    commit_message = "Python upload " + dt_string
    
    #check if already exists
    all_files = []
    contents = repo.get_contents("")
    while contents:
        file_content = contents.pop(0)
        if file_content.type == "dir":
            contents.extend(repo.get_contents(file_content.path))
        else:
            file = file_content
            all_files.append(str(file).replace('ContentFile(path="','').replace('")',''))

    if filename in all_files:
        #update existing
        file = repo.get_contents(filename)
        repo.update_file(filename, commit_message, csv_data, file.sha)
    else:
        repo.create_file(filename, commit_message, csv_data)
        
    return

def dw_timestamp(chart_id_list):
    
# =============================================================================
#   adds timestamp to the byline in the datawrapper chart for given list of chart ids
#   no longer used
# =============================================================================
    
    for chart_id in chart_id_list:
        properties = dw.chart_properties(chart_id)["metadata"]

        #get notes for chart
        notes = properties["annotate"]["notes"]

        timestamp = dt.datetime.now().strftime("%I%p, %d %b ").lstrip("0").replace(" 0", " ")
        timestamp = timestamp.replace("PM", "pm").replace("AM", "am")

        properties["describe"]["byline"] = "The Spectator (" + chart_id +") Updated " + timestamp

        dw.update_metadata(chart_id, properties)
        dw.publish_chart(chart_id, display =False)
    
    return

def dw_note_update(chart_id_list, latest_data, when_update, time_stamp=False):
    
# =============================================================================
#   adds publish date to the notes in the datawrapper chart for given list of chart ids
# ============================================================================= 

    for chart_id in chart_id_list:
        properties = dw.chart_properties(chart_id)["metadata"]
        
        #get notes for chart
        notes = properties["annotate"]["notes"]
        #find "Most recent"
        
        if time_stamp:
            timestamp = dt.datetime.now().strftime("%I%p, %d %b").lstrip("0").replace(" 0", " ")
            timestamp = timestamp.replace("PM", "pm").replace("AM", "am")     
        else:
            timestamp = dt.datetime.now().strftime("%d %b").lstrip("0").replace(" 0", " ")
        
        if (notes.startswith("Figures to") | (notes=="")):
            notes = "Figures to " + latest_data + ", published " + timestamp + ". "+ when_update
        else:        
            start_str = notes.find("<br>Figures to")
            notes = notes if start_str ==-1 else notes[:start_str]
            notes = notes + "<br>Figures to " + latest_data + ", published " + timestamp + ". " + when_update
        
        properties["annotate"]["notes"] = notes
        
        dw.update_metadata(chart_id, properties)
        dw.publish_chart(chart_id, display =False)
        
    return

def dw_subhead_update(chart_id_list, latest_data, when_update, time_stamp=False):
    
# =============================================================================
#   adds publish date to the subhead in the datawrapper chart for given list of chart ids
# ============================================================================= 

    for chart_id in chart_id_list:
        properties = dw.chart_properties(chart_id)["metadata"]
    
        #get notes for chart
        subhead = properties["describe"]["intro"]
    
        if time_stamp:
            timestamp = dt.datetime.now().strftime("%I%p, %d %b").lstrip("0").replace(" 0", " ")
            timestamp = timestamp.replace("PM", "pm").replace("AM", "am")     
        else:
            timestamp = dt.datetime.now().strftime("%d %b").lstrip("0").replace(" 0", " ")
            
        #want to replace subhead before any html anchor which we use as a marker for buttons
        
        break_point = subhead.find("<a target")
        if break_point ==-1:
            #no <br> so replace whole string
            subhead = "Updated " + timestamp
        else:
            subhead = "<b>Updated " + timestamp + "<b> " + subhead[break_point:]
    
        properties["describe"]["intro"] = subhead
        dw.update_metadata(chart_id, properties)
        dw.publish_chart(chart_id, display =False)
    
    return

# =============================================================================
# Adds Datawrapper flag codes to list of country codes
# =============================================================================
def add_flag_codes(index_list):
    
    flag_codes_dict = pd.read_csv("Flag codes.csv", index_col=0)["code"].to_dict()
    
    out_list = []
    for country in index_list:
        out_list = out_list + [flag_codes_dict[country] + " " + country]
    
    return out_list


def query_API(areaType = "utla", data_requested = "newCasesBySpecimenDate", name_data = "Cases"):
    
# =============================================================================
# Queries PHE API for single data set and deals with date formatting
# =============================================================================

    query_filter = ["areaType=" + areaType]
    data_requested = {
        "date" : "date",
        "areaName": "areaName",
        "areaCode": "areaCode",
        name_data : data_requested
        }
    api = Cov19API(filters=query_filter,    
                   structure=data_requested)
    
    df = api.get_dataframe()  
    
    df["date"]=pd.to_datetime(df["date"], dayfirst=True).dt.date   
    df.set_index("date", inplace = True)  
    return df.iloc[::-1]  #this reverses the order



















