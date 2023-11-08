import base64
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import mimetypes
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

# If modifying these scopes, delete the file token.json.
# SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
SCOPES = ['https://www.googleapis.com/auth/gmail.send']


def get_service():
    """Shows basic usage of the Gmail API.
    Lists the user's Gmail labels.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('./config/token.json'):
        creds = Credentials.from_authorized_user_file('./config/token.json', SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                './config/credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('./config/token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        # Call the Gmail API
        service = build('gmail', 'v1', credentials=creds)
        return service

    except HttpError as error:
        # TODO(developer) - Handle errors from gmail API.
        print(f'An error occurred: {error}')


def create_message_with_attachment(
        sender, to, subject, message_text, files):
    """Create a message for an email.
    Args:
      sender: Email address of the sender.
      to: Email address of the receiver.
      subject: The subject of the email message.
      message_text: The text of the email message.
      file: List with each item being the path to a file to be attached.
    Returns:
      An object containing a base64url encoded email object.
    """
    # set to, from, subject line
    message = MIMEMultipart()
    message['to'] = ", ".join(to)
    message['from'] = sender
    message['subject'] = subject
    # add the message body text
    msg = MIMEText(message_text)
    message.attach(msg)

    # handle adding the attachment
    for file in files:
        content_type, encoding = mimetypes.guess_type(file)
        main_type, sub_type = content_type.split('/', 1)
        if main_type == 'text':
            fp = open(file, 'rb')
            msg = MIMEText(fp.read(), _subtype=sub_type, _charset='UTF-8')
            encoders.encode_base64(msg)
            fp.close()
        elif main_type == 'image':
            fp = open(file, 'rb')
            msg = MIMEImage(fp.read())
            encoders.encode_base64(msg)
            fp.close()
        else:
            fp = open(file, 'rb')
            msg = MIMEBase(main_type, sub_type)
            msg.set_payload(fp.read())
            encoders.encode_base64(msg)
            fp.close()
        filename = os.path.basename(file)
        msg.add_header('Content-Disposition', 'attachment', filename=filename)
        message.attach(msg)

    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}


def send_message(service, user_id, message):
    """Send an email message.
    Args:
      service: Authorized Gmail API service instance.
      user_id: User's email address. The special value "me"
      can be used to indicate the authenticated user.
      message: Message to be sent.
    Returns:
      Sent Message.
    """
    res = service.users().messages().send(userId=user_id, body=message).execute()
    return res


def get_recipients():
    recipients = []
    with open('./config/email_recipients.txt', 'r') as f:
        lines = f.readlines()
        for line in lines:
            recipients.append(line.replace('\n', ''))
    return recipients


if __name__ == "__main__":
    service = get_service()
    recipients = get_recipients()
    print(f'recipients: {recipients}')
    message = create_message_with_attachment(sender="thwaites.ice.server@gmail.com",
                                             to=recipients,
                                             subject='test',
                                             message_text='testing 123',
                                             files=['ice_cover.zip', './rasters/composite.tif', 'SendMail.py'])
    send_message(service, "me", message)
    print('Sent test message.')
