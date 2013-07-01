#!/usr/bin/python

# noisebridge-baron
#
# Interfaces with the pay phone keypad at the entrance to Noisebridge,
# opening the gate for those who know one of the entry codes.  Requires
# the python-serial (pyserial) module.
#
# Authors have included:
#   davidme
#   jesse
#   mct

import urllib, urllib2, json
import logging
import serial
import argparse
import sys
import os
from datetime import datetime, timedelta

from time import sleep

keypad = None
codes_path = None
codes = []
codeset = CodeSet()
promiscuous = False

class CodeException(Exception):
  pass
class CodeExpired(CodeException):
  pass
def code_from_string(code_string, valid_for = seconds_in_one_day):
  """Create a new code from a string of digits. Valid for one day, by default."""
  c = Code()
  c.code = code_string
  c.creation_time = datetime.now()
  c.validity_period = timedelta(seconds = valid_for)
  c.valid()
  return c
class Code(object):
  code = None
  creation_time = None
  # -1 is used to indicate that a code is good forever.
  validity_interval = -1
  enabled = True
  log = []
  def assert_validty(self):
    if not (self.code and len(self.code) > 0 and self.code.isdigit()):
      raise CodeException("Code string is not a string of digits.")
    if not isinstance(self.creation_time, datetime):
      raise CodeException("Code creation_time is not a datetime.datetime.")
    if not isinstance(self.validity_interval, int):
      raise CodeException("Code validity_interval is not an integer.")
    if not self.enabled:
      raise CodeExpired("This code is disabled")
    if self.is_expired():
      raise CodeExpired("This code has expired.")
    return True
  def is_expired(self):
    if (self.validity_interval == -1):
      return False
    else:
      now = datetime.now()
      expiration_time = creation_time + timedelta(seconds = self.validity_interval)
      return (now >= expiration_time)
  def disable(self):
    self.enabled = False
  def enable(self):
    self.enabled = True
class CodeSet(object):
  codes = {}
  def add(self, code):
    code.assert_validty()
    if self.get(code):
      raise Exception("This code already exists in the %s" % self.__class__.__name__)
    self.codes[code.code] = code
  def get(self, code_string):
    return self.codes.get(code_string)
  def check(self, code_string):
    c = self.get(code_string)
    if c and c.assert_validty():
      return True
    else:
      return False
  def update(self, code):
    logging.info('Updating %s with new code object for %s' % (self.__class__.__name__, code.code))
    self.codes[code.code] = code
  def disable(self, code_string):
    logging.info('Disabling code %s from the %s' % (code_string, self.__class__.__name__))
    c = self.codes[code_string]
    if not c:
      raise Exception("There is no code %s in the %s." % (code_string, self.__class__.__name__))
    c.disable()

# Operations on code storage
# - Set a code
# - Check for code presence
# - Check for code validity
# - Disable a code
# - Update code expiration date

def open_serial(filename):
    global keypad

    try:
        logging.debug("Opening %s", filename)
        keypad = serial.Serial(filename, 300, bytesize=serial.EIGHTBITS,
                               parity=serial.PARITY_NONE,
                               stopbits=serial.STOPBITS_ONE,
                               xonxoff=0,
                               rtscts=0,
                               writeTimeout=10)
    #except serial.serialutil.SerialException as e:
    except Exception as e:
        logging.error("Serial port setup failed: %s: %s: %s", filename, type(e), str(e))
        raise

last_mtime = 0
def load_codes(filename=None):
    """
    Loads a list of valid access codes from the specified filename.  Lines
    starting with '#' are comments.  All other lines must contain numeric codes
    which grant access, one code per line.

    Each time this function is called, it will only re-open the codes file it's
    mtime since the last call has changed.
    """

    global codes_path, last_mtime, codeset

    if not filename:
        filename = codes_path

    try:
        mtime = os.stat(filename).st_mtime
        if mtime == last_mtime:
            logging.debug("mtime has not changed, not reloading %s", filename)
            return
        else:
            last_mtime = mtime

        new_codes = []
        lineno = 0

        for line in open(filename):
            lineno += 1
            code = line.split("#")[0].strip().rstrip()
            if not code:
                continue
            if not code.isdigit():
                logging.warning("%s:%d: Ignoring malformed line" % (filename, lineno))
            new_codes.append(code)

        logging.info("Loaded %d codes from %s" % (len(new_codes), filename))

        new_codeset = CodeSet()
        for code in new_codes:
          c = Code()
          c.code = code
          c.valid()
          new_codeset.add(c)
        codeset = new_codeset

    except Exception as e:
        logging.error("Error loading %s: %s: %s" % (filename, type(e), str(e)))
        raise

def open_gate(endpoint='http://api.noisebridge.net/gate/', command={'open':1}):
    """
    Uses the Noisebridge API to open the front gate.
    """
    try:
        results = urllib2.urlopen(endpoint, urllib.urlencode(command)).read()
        results = json.loads(results)
    except urllib2.HTTPError, e:
        logging.error("error: HTTP Error %s when calling <%s>: %s" % (endpoint, e.code, e.read()))
        return False
    except urllib2.URLError, e:
        logging.error("error: Could not reach <%s> data is %s" % (endpoint, e.args))
        return False
    except ValueError:
        logging.error("error: Could not decode JSON from <%s>: %r" % results)
        return False

    if results.get('open', False):
        return True
    else:
        return False

def check_code(code, reload_codes=True):
    global codeset

    if reload_codes:
        load_codes()

    if code and codeset.get(code):
        logging.info("Opening the door for code %s" % code)

        if open_gate():
            keypad.write('BH')  # Blue LED, Happy sound
        else:
            keypad.write('SR')  # Sad sound, Red LED
            sleep(0.2)
            keypad.write('QSR') # Quiet, Sad sound, Red LED
            sleep(0.2)
            keypad.write('QSR') # Quiet, Sad sound, Red LED
    else:
        logging.info("Not opening the door for bad code %s" % code)
        keypad.write('SR') # Sad sound, Red LED

def send_debug(buf):
    global keypad
    logging.debug("Sending %s" % repr(buf))
    keypad.write(buf)

def do_test():
    global codeset

    send_debug('SR'); sleep(1) # Sad Red
    send_debug('SG'); sleep(1) # Sad Green
    send_debug('SB'); sleep(1) # Sad Blue
    send_debug('Q');  sleep(1) # Quiet
    send_debug('HR'); sleep(1) # Happy Red
    send_debug('HG'); sleep(1) # Happy Green
    send_debug('HB'); sleep(1) # Happy Blue

    codeset = Codeset()
    c = Code()
    c.code = 42
    codeset.add(c)
    check_code("42", reload_codes=False)

def door_loop():
    global keypad

    # Specify a timeout with pyserial, to have read() return after N seconds
    # with no input.  If the keypad is idle for this long, we'll detect it by
    # reading zero bytes, and clear the input buffer.
    keypad.timeout = 10

    input_buffer = ""

    while True:
        try:
            char = keypad.read(1)

            if not char:
                logging.debug("Keypad read timeout, flushing input buffer")
                input_buffer = ""
                continue

            if promiscuous:
                logging.info("Opening door in promiscuous mode")
                open_gate()
                continue

            if char == "*":
                logging.debug("Read character %s, flushing input buffer", repr(char))
                input_buffer = ""

            elif char == "#":
                if not input_buffer:
                    logging.debug("Read character %s, but ignoring empty code", repr(char))
                else:
                    logging.debug("Read character %s, checking code", repr(char))
                    check_code(input_buffer)
                input_buffer = ""

            elif char.isdigit():
                logging.debug("Read character %s", repr(char))
                input_buffer += char

            else:
                logging.debug("Ignoring non-digit character: %s" % repr(char))

        except Exception as e:
            logging.error("Keypad error: %s: %s" % (type(e), str(e)))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port",       required=True,          help="Serial port")
    parser.add_argument("--codefile",   required=True,          help="File containing list of valid access codes")
    parser.add_argument("--logfile",    default=None,           help="Write output to logfile, rather than standard out")
    parser.add_argument("--debug",      action="store_true",    help="Enable debugging output")
    parser.add_argument("--test",       action="store_true",    help="Execute single-shot keypad output test")
    parser.add_argument("--promiscuous",action="store_true",    help="Enable any keypress at all to open the door")
    args = parser.parse_args()

    codes_path = args.codefile
    promiscuous = args.promiscuous

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(format='%(asctime)s %(levelname)-7s %(message)s', datefmt='%Y-%m-%d %H:%M:%S', level=level, filename=args.logfile)

    try:
        open_serial(args.port)
    except:
        logging.error("Serial port setup failed.  Exiting.")
        sys.exit(1)

    if args.test:
        do_test()
        sys.exit()

    logging.info("Starting Baron")
    load_codes()
    door_loop()
