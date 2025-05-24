import datetime
import os.path
import zoneinfo
from tzlocal import get_localzone_name

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_system_tz() -> str | None:
    #Gets local timezone from system
    try:
        return get_localzone_name()
    except Exception as e:
        print(f"Error getting system timezone: {e}")

#Store local timezone in global var
TIMEZONE = get_system_tz()

def convert_str_to_time(time_str: str) -> datetime.time | None:
    #Converts string input in the format HH:MM into timezone.time object
    try:
        return datetime.datetime.strptime(time_str, "%H:%M").time()
    except ValueError as e:
        print(f"Invalid time format: {e}")

def convert_str_to_date(date_str: str) -> datetime.date | None:
    #Converts string input in the format dd-mm-YYYY to a datetime.date object
    try:
        return datetime.datetime.strptime(date_str, "%d-%m-%Y").date()
    except ValueError as e:
        print(f"Invalid date format: {e}")


def authenticate():
    #Creates the json access and refresh tokens to authenticate user to the application
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json", SCOPES
            )
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return creds


def get_events_on_day(creds, date_str: str):
    #Returns a list of all events on a given day
    try:
        service = build("calendar", "v3", credentials=creds)

        #Convert string date input to the correct datetime format
        date = convert_str_to_date(date_str)
        start_datetime = datetime.datetime.combine(date, datetime.time.min).isoformat() + 'Z'
        end_datetime = datetime.datetime.combine(date, datetime.time.max).isoformat() + 'Z'

        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_datetime,
            timeMax=end_datetime,
            singleEvents=True,
            orderBy='startTime'
        ).execute()


        events = events_result.get('items', [])

        return events

    except HttpError as error:
        print(f"An error occurred: {error}")
        quit()


def add_event(creds, date_str: str, start_time_str: str, duration: int, summary: str)-> None:
    #Adds an event to the Google calendar

    #Convert date and time to the correct format for request body
    date = convert_str_to_date(date_str)
    start_time = convert_str_to_time(start_time_str)
    start_dt = datetime.datetime.combine(date, start_time, tzinfo=zoneinfo.ZoneInfo(TIMEZONE))
    end_dt = start_dt + datetime.timedelta(hours=duration)
    start_formatted = start_dt.isoformat()
    end_formatted = end_dt.isoformat()


    #Create request body
    event = {
        'summary': summary,
        'start': {
            'dateTime': start_formatted,
            'timeZone': TIMEZONE,
        },
        'end': {
            'dateTime': end_formatted,
            'timeZone': TIMEZONE,
        },
        'reminders': {
            'useDefault': True,
        }
    }

    #Send API call to insert event into the calendar
    try:
        service = build("calendar", "v3", credentials=creds)
        event = service.events().insert(calendarId='primary', body=event).execute()
        print(f"Event created: {event.get('htmlLink')}")

    except HttpError as error:
        print(f"An error occurred: {error}")
        quit()

def print_events(events):
    #Prints list of events to the terminal (for debug purposes)
    if not events:
      print("No upcoming events found.")
      return

    for event in events:
      start = event["start"].get("dateTime", event["start"].get("date"))
      print(start, event["summary"])

def main():
    creds = authenticate()

    add_event(creds, "24-05-2025", "21:00", 2, "Test API")

    events = get_events_on_day(creds, "24-05-2025")
    print_events(events)

if __name__ == "__main__":
  main()


