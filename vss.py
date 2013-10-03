#!/usr/bin/python

# import GPIO library
import RPi.GPIO as GPIO
    
import ConfigParser
import sys
import time

# add your path to the fitlib. include the fitlib directory, because we don't
# want the whole fitlib, but just loglib
sys.path.append('C:\\dummylibraryfolder\\homefolder\\fitlib\\')

import loglib

import smtplib
from email.mime.text import MIMEText

# create log object and starting logging
log = loglib.Log(filename = 'vss.log', outputfolder = '.', timestamp = True)

# first of all we need our configuration
log.write('Reading configuration file')
cfg = ConfigParser.RawConfigParser()
cfg.read('vss.conf')

# emtpy error log
conf_errors = ''

# experiment name
exp_name = cfg.get('General', 'Experiment-Name')
# revision of the Raspberry. Reason is that the pins have changed slightly.
rpi_rev = cfg.get('General', 'PPi-Revision')

# we create a list of email addresses to alert.
emails_list = cfg.items('Operators')
log.write('Alerting the following operators: ' + str(emails_list))
    
# read email-server configuration
try:
    # in some cases we don't want email
    email = cfg.getboolean('Email-Account', 'email')
    if email is True:
        emails_string = ''
        emails_list = cfg.items('Operators')
        for operator_id, email in emails_list:
            emails_string += email + '; '

        email_username = cfg.get('Email-Account', 'username')
        email_password = cfg.get('Email-Account', 'password')
        email_server = cfg.get('Email-Account', 'server')
        
        log.write('Email configured')
    
    elif email is False:
        log.write('Not using email notifications')
except:
    log.write('Configuration for email notification could not be read!')
    
# function to send emails
def send_email_to_op(text):
    global email
    if email is True:
        try:
            # this is the routine to send email. pretty straightforward.
            # we use TLS, because we can.
            s = smtplib.SMTP(email_server)
            s.starttls()
            s.login(email_username, email_password)
            msg = MIMEText(text)
            msg['Subject'] = exp_name + ' Vacuum System Warning'
            msg['From'] = exp_name
            for operator_id, email in emails_list:
                msg['To'] = email
            s.sendmail(email, 'johannes.postler@uibk.ac.at', msg.as_string())
            s.quit()
        except:
            log.write('Could not inform operator. Sending email failed.')
            log.write('The original message was:')
            log.write(text)
            
            # switch on the LED to inform the operator, that something is weird
            GPIO.output(error_led, True)
    elif email is False:
        log.write('Email supressed. Text was: ' + text)
    

# at most we have six relays from the pfeiffer maxigauge
relays = dict(A = [], B = [], C = [], D = [], E = [], F = [])

# dictionary for pin number to GPIO-channel translation
if rpi_rev == 'rev1':
    pin2channel = {3: 0, 5: 1, 8: 14, 10: 15, 12: 18, 16: 23, 18: 24, 22: 25, 24: 8, 26: 7, 7: 4, 11: 17, 13: 21, 15: 22, 19: 10, 21: 9, 23: 11}
elif rpi_rev == 'rev2':
    pin2channel = {3: 2, 5: 3, 8: 14, 10: 15, 12: 18, 16: 23, 18: 24, 22: 25, 24: 8, 26: 7, 7: 4, 11: 17, 13: 27, 15: 22, 19: 10, 21: 9, 23: 11}

# set the numbering of channels to BCM mode
GPIO.setmode(GPIO.BCM)

# clean up all the channels in case there is something left
GPIO.cleanup()

# read cfg file and fill relay dictionary
for relay in relays:
    log.write('Setting up Relay ' +  relay)
    # each dict-entry is a dict by itself containing all the info
    relays[relay] = dict()
    try:
        relays[relay]['pin'] = cfg.getint('Relay ' + relay, 'pin')
        relays[relay]['name'] = cfg.get('Relay ' + relay, 'name')
        relays[relay]['warning'] = cfg.getboolean('Relay ' + relay, 'warning')
        relays[relay]['shutdown'] = cfg.getboolean('Relay ' + relay, 'shutdown')
        relays[relay]['active'] = cfg.getboolean('Relay ' + relay, 'active')
    except:
        conf_errors += ('Configuration Errors in Section %s \r\n' % relay)
    
    # convert the pin name to the according channel. set as input
    try:
        relays[relay]['channel'] = pin2channel[relays[relay]['pin']]
        if relays[relay]['active'] is True:
            GPIO.setup(relays[relay]['channel'], GPIO.IN)
    except KeyError:
        conf_errors += ('Pin does not exist for relay %s \r\n' % relay)
        
# read the switches to shut down in case of alert
shutdown_switches = cfg.items('Shutdown')
switches = []
for name, pin in shutdown_switches:
    # translate to channel
    channel = pin2channel[int(pin)]
    # for each switch we try to set it up and shut it down immediately
    try:
        GPIO.setup(channel, GPIO.OUT)
        GPIO.output(channel, False)
    except:
        conf_errors += 'Could not set up Shutdown-Switch at pin: ' + pin
        
    switches.append(channel)

# no we set up our error LED. let it glow from the beginning, since the
# user should confirm the start up
try:
    error_led = cfg.getint('Error-LED', 'pin')
    error_led = pin2channel[error_led]
    GPIO.setup(error_led, GPIO.OUT)
    GPIO.output(error_led, True)
except:
    conf_errors += 'Error-LED pin not found\r\n'
    
# no we set up our reset button. 
try:
    reset_button = cfg.getint('Reset-Button', 'pin')
    reset_button = pin2channel[reset_button]
    GPIO.setup(reset_button, GPIO.IN)
except:
    conf_errors += 'Reset-Button pin not found\r\n'
    
# now we read what to shutdown
try:
    shutdown_channels = []
    shutdown_pins = cfg.items('Shutdown')
    for pinname, shutdown_pin in shutdown_pins:
        shutdown_channels.append(pin2channel[int(shutdown_pin)])
except:
    conf_errors += 'Could not read pins to shutdown.\r\n'

# something wrent wrong in the configuration file. we should abort and 
# send email if possible
if conf_errors is not '':
    send_email_to_op('Configuration failure. Stopping.')
    log.write(conf_errors)
    sys.exit('Configuration failure. Stopping.')
    
# function to shutdown the experiment
def emergency_shutdown(channel):
    # first shut down everything!
    for switch in switches:
        GPIO.output(switch, False)
            
    # switch on LED
    GPIO.output(error_led, True)
    
    # reverse lookup which relay sent the signal
    # not beautiful, but it works
    for relay in relays:
        if relays[relay]['channel'] == channel:
            error_relay = relay
    
    # send email
    send_email_to_op('Emergency Shutdown of %s, because relay %s reported high pressure.' % (exp_name, relays[error_relay]['name']))
    
    # log
    log.write('Emergency Shutdown of %s, because relay %s reported high pressure.' % (exp_name, relays[error_relay]['name']))
    
def confirm(channel):
    # for startup we always check whether all relays show the status ok (1 or True).
    startup = True
    
    log.write('Checking relays to start up.')
    for relay in relays:
        if relays[relay]['active'] is True:
            if GPIO.input(relays[relay]['channel']) != 1:
                startup = False
        
    #ready to go?
    if startup is True:
        # start the switches
        for switch in switches:
            GPIO.output(switch, True)
            
        # switch off LED
        GPIO.output(error_led, False)
        
        # log
        log.write('Startup complete.')
    elif startup is False:
        log.write('Startup failed. Check all the pressures.')
        send_email_to_op('Startup failed. Check all the pressures.')
        
def send_warning(channel):
    # switch on LED
    GPIO.output(error_led, True)
    
    # reverse lookup which relay sent the signal
    # not beautiful, but it works
    for relay in relays:
        if relays[relay]['channel'] == channel:
            error_relay = relay
    
    # send email
    send_email_to_op('%s WARNING: relay %s reported high pressure.' % (exp_name, relays[error_relay]['name']))
    
    # log
    log.write('%s WARNING: relay %s reported high pressure.' % (exp_name, relays[error_relay]['name']))
        
# add the event callback for the reset button
GPIO.add_event_detect(reset_button, GPIO.RISING, bouncetime = 2000)
GPIO.add_event_callback(reset_button, confirm)

# final startup routine: add the event callbacks to active relays
        
for relay in relays:
    # only for active ones
    if relays[relay]['active'] is True:
        GPIO.add_event_detect(relays[relay]['channel'], GPIO.FALLING)
        # we want the shutdown first, as the two callbacks are executed one after the other
        if relays[relay]['shutdown'] is True:
            GPIO.add_event_callback(relays[relay]['channel'], emergency_shutdown)
        if relays[relay]['warning'] is True:
            GPIO.add_event_callback(relays[relay]['channel'], send_warning)

# lets hit the main routine
try:
    while(True):
        log.write('VS status is good. Going to sleep.')
        time.sleep(3600)
except:
    send_email_to_op('An exception occured or the program has been terminated. VS on %s is going down.' % exp_name)
finally:
    GPIO.cleanup()