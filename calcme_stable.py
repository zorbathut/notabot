#!/usr/bin/python

"""
CalcMe

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; version 2 of the license only.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

Ben Wilhelm (zorba@pavlovian.net)
"""

import string
from ircbot import SingleServerIRCBot
from irclib import nm_to_n, nm_to_h, irc_lower, ip_numstr_to_quad, ip_quad_to_numstr
import MySQLdb
import time as time
import sys as sys
import traceback as traceback
import re as re
import copy

g_queryCount = 0
g_changeCount = 0
g_startDate = 0

g_username = ""
g_passwd = ""
g_dbhost = ""
g_dbname = ""

g_lastuser = ""
g_lastcommand = ""

def itime():
  return int(time.time())

def initDb():
  global db, g_username, g_passwd, g_dbhost, g_dbname
  db = MySQLdb.connect(host=g_dbhost,user=g_username,passwd=g_passwd,db=g_dbname)
  print db

def safeExecute(cursor, string, params):
  try:
    rv=cursor.execute(string, params)
    return cursor, rv
  except MySQLdb.OperationalError:
    print "Fuck, caught OperationalError"
    initDb()
    cursor=db.cursor()
    rv=cursor.execute(string, params)
    return cursor, rv

def dumpCrashlog(who, what, command):
  global db
  c = db.cursor()
  c, rv = safeExecute(c, 'INSERT INTO crashlog ( time, who, command, what ) VALUES ( NOW(), %s, %s, %s )', (who, command, what))

def getPermissionDict():
  levels = {-1:'IGNORE', 0:'USER', 1:'PUBLIC', 2:'CHANGE', 3:'AUTHORIZE', 4:'GOD'}
  #print [(value, key) for key, value in levels.iteritems()]
  revlevels = dict([(value, key) for key, value in levels.iteritems()])
  return levels, revlevels

def greaterPermission(lhs, rhs):
  levels, revlevels = getPermissionDict()
  lhsl = revlevels[lhs]
  rhsl = revlevels[rhs]
  return levels[max(lhsl, rhsl)]
  
def adequatePermission(needed, have):
  levels, revlevels = getPermissionDict()
  #print "got", have, "needed", needed, "result", revlevels[needed] <= revlevels[have]
  return revlevels[needed] <= revlevels[have]
  
def getNickPermissions(nick):
  global db
  c=db.cursor()
  c, rv = safeExecute(c, 'SELECT permlev FROM users WHERE username = %s', (nick,))
  if rv == 0:
    return "USER"
  else:
    return c.fetchone()[0]

def getPermissions(user_host, channel):
  global db
  c=db.cursor()
  c, rv = safeExecute(c, 'SELECT max(users.permlev), min(users.username) FROM users, masks WHERE users.username = masks.username AND %s LIKE masks.mask', (user_host,)) # Why min? Because there might technically be multiple matches, and this makes things less likely to be blamed on me. (There probably shouldn't be multiple matches. Todo: rig things to notify someone if there are multiple matches)
  perm, username = c.fetchone()
  nick = nm_to_n(user_host)
  if perm == None:
    perm = "USER"
    username = nick
  if channel.is_oper(nick):
    perm = greaterPermission(perm, 'AUTHORIZE')
  if perm != 'IGNORE' and channel.is_voiced(nick):
    perm = greaterPermission(perm, 'PUBLIC')
  return perm, username

def getMatch(user):
  global db
  c=db.cursor()
  c, rv = safeExecute(c, 'SELECT username FROM masks WHERE %s LIKE masks.mask', (user,))
  if rv == 0:
    return ""
  else:
    return c.fetchone()[0]

def getEntry(entry):
  global db
  c=db.cursor()
  c, rv = safeExecute(c, 'SELECT value FROM current WHERE name = %s', (entry,))
  if rv == 0:
    return ""
  return c.fetchone()[0]
  
def getVersionedEntry(entry, version):
  global db
  c=db.cursor()

  version = str(version)
  if str(version[0]) == '-':
    c, rv = safeExecute(c, 'SELECT value, username, modifier, changed FROM versions WHERE name = %s AND version = (SELECT max(version)+%s+1 FROM versions WHERE name = %s)', (entry, version, entry))
  else:
    c, rv = safeExecute(c, 'SELECT value, username, modifier, changed FROM versions WHERE name = %s AND version = %s', (entry, version))
  if rv == 0:
    return None, None, None, None
  else:
    return c.fetchone()
  
def getCount(entry):
  global db
  c=db.cursor()
  c, rv = safeExecute(c, 'SELECT count FROM current WHERE name = %s', (entry,))
  if rv == 0:
    return 0
  return c.fetchone()[0]
  
def getLastVersion(entry):
  global db
  c=db.cursor()
  c, rv = safeExecute(c, 'SELECT max( version ) FROM versions WHERE name = %s', (entry,))
  if rv == 0:
    raise Error
  return c.fetchone()[0]

def incrementCount(entry):
  global db
  c=db.cursor()
  c, rv = safeExecute(c, 'UPDATE current SET count = count + 1 WHERE name = %s', (entry,))
  if rv == 0:
    c, rv = safeExecute(c, 'INSERT INTO current ( name, value, count ) VALUES ( %s, %s, %s )', (entry, "", 1))
    if rv == 0:
      raise Error, "Can't seem to increment for some reason."

def setCount(entry, count):
  global db
  c=db.cursor()
  #print count, entry
  c, rv = safeExecute(c, 'UPDATE current SET count = %s WHERE name = %s', (count,entry))
  if rv == 0:
    c, rv = safeExecute(c, 'SELECT * FROM current WHERE count = %s AND name = %s', (count,entry))
    if rv == 0:
      c, rv = safeExecute(c, 'INSERT INTO current ( name, value, count ) VALUES ( %s, %s, %s )', (entry, "", count))
      raise Error, "Can't seem to set for some reason."

def changeEntry(entry, data, user_host, user_id):
  global db
  c=db.cursor()
  c, rv = safeExecute(c, 'SELECT max( version ) FROM versions WHERE name = %s', (entry,))
  if rv == 0:
    raise Error, "Select is fucked."
  nextversion = c.fetchone()[0]
  if nextversion == None:
    nextversion = 0
  else:
    nextversion = nextversion + 1
  c, rv = safeExecute(c, 'INSERT INTO versions ( name, version, modifier, username, value, changed ) VALUES ( %s, %s, %s, %s, %s, NOW() )', (entry, nextversion, user_host, user_id, data))
  if rv == 0:
    raise Error, "Versioning is fucked."
  c, rv = safeExecute(c, 'UPDATE current SET value = %s WHERE name = %s', (data, entry))
  if rv == 0:
    c, rv = safeExecute(c, 'SELECT * FROM current WHERE value = %s AND name = %s', (data,entry))
    if rv != 0:
      raise Error, "Changed entry to already existing entry."
    c, rv = safeExecute(c, 'INSERT INTO current ( name, value, count ) VALUES ( %s, %s, %s )', (entry, data, 0))
    if rv == 0:
      raise Error, "Current is fucked weirdly."

def apropos(data, key=False, value=False):
  global db
  c=db.cursor()
  if key == 0 and value == 1:
    c, rv = safeExecute(c, 'SELECT name FROM current WHERE value != "" AND value LIKE CONCAT("%%", %s, "%%") ORDER BY name', (data,))
    if rv == 0:
      return "";
  elif key == 1 and value == 0:
    c, rv = safeExecute(c, 'SELECT name FROM current WHERE value != "" AND name LIKE CONCAT("%%", %s, "%%") ORDER BY name', (data,))
    if rv == 0:
      return "";
  elif key == 1 and value == 1:
    c, rv = safeExecute(c, 'SELECT name FROM current WHERE value != "" AND ( name LIKE CONCAT("%%", %s, "%%") OR value LIKE CONCAT("%%", %s, "%%") ) ORDER BY name', (data,data))
    if rv == 0:
      return "";
  else:
    raise Error, "Apropos is fucked."
  output = [];
  while 1:
    tv = c.fetchone();
    if tv == None:
      break
    output.append(tv[0])
  return output
  
def getCalcCount():
  global db
  c=db.cursor()
  c, rv = safeExecute(c, 'SELECT COUNT(name) FROM current WHERE value != ""', ())
  if rv == 0:
    raise Error, "No calcs? WTF?"
  return c.fetchone()[0]
  
def globToLike(dat):
  return dat.replace("\\","\\\\").replace("%","\%").replace("_","\_").replace("*","%").replace("?","_")
  
def showhost(nick):
  global db
  c=db.cursor()
  c, rv = safeExecute(c, 'SELECT origmask FROM masks WHERE username = %s ORDER BY mask', (nick,))
  if rv == 0:
    return []
  output = [];
  while 1:
    tv = c.fetchone();
    if tv == None:
      break
    output.append(tv[0])
  return output
  
def rmhost(user, mask, source):
  global db
  c=db.cursor()
  c, nrv = safeExecute(c, 'INSERT INTO userver ( modifier, command, target, data, time ) VALUES ( %s, %s, %s, %s, NOW() )', (source, "rmhost", user, mask))
  if nrv == 0:
    raise Error, "Validation failed!"
  c, rv = safeExecute(c, 'DELETE FROM masks WHERE username = %s AND mask = %s', (user, globToLike(mask)))
  if rv == 0:
    return 0
  else:
    return 1
    
def addhost(user, mask, source):
  global db
  if len(mask)>255:
    mask = mask[0:255]   # yeah, whatever
  c=db.cursor()
  c, rv = safeExecute(c, 'SELECT username FROM masks WHERE username = %s AND mask = %s', (user, globToLike(mask)))
  if rv == 1:
    return 0
  c, nrv = safeExecute(c, 'INSERT INTO userver ( modifier, command, target, data, time ) VALUES ( %s, %s, %s, %s, NOW() )', (source, "addhost", user, mask))
  if nrv == 0:
    raise Error, "Validation failed!"
  c, rv = safeExecute(c, 'INSERT INTO masks ( username, mask, origmask ) VALUES ( %s, %s, %s )', (user, globToLike(mask), mask))
  if rv == 0:
    return 0
  else:
    return 1

def chperm(user, newperm, source):
  levels, revlevels = getPermissionDict()
  newperm = newperm.upper()
  if not newperm in revlevels:
    return 0
  c=db.cursor()
  c, nrv = safeExecute(c, 'INSERT INTO userver ( modifier, command, target, data, time ) VALUES ( %s, %s, %s, %s, NOW() )', (source, "chperm", user, newperm))
  if nrv == 0:
    raise Error, "Validation failed!"
  c, rv = safeExecute(c, 'UPDATE users SET permlev = %s WHERE username = %s', (newperm, user))
  if rv == 0:
    c, rv = safeExecute(c, 'SELECT username FROM users WHERE permlev = %s AND username = %s', (newperm, user))
    if rv == 1:
      return 1
    c, rv = safeExecute(c, 'INSERT INTO users ( permlev, username ) VALUES ( %s, %s )', (newperm, user))
    if rv == 0:
      raise Error, "Validation failed!"
    else:
      return 1
  else:
    return 1

def toki(instring):
  out = [instring]
  while ' ' in out[len(out) - 1]:
    out[len(out)-1:] = out[len(out) - 1].strip().split(' ', 1)
  return out

class TestBot(SingleServerIRCBot):
  class ParseModule:
    def __init__(self, permission, pattern, function, helptext = None, visible = True, confused_help = True, private_only = False, parsechecker = None):
      self.permission = permission
      self.pattern = pattern
      self.function = function
      self.confused_help = confused_help
      self.visible = visible
      self.helptext = helptext;
      self.private_only = private_only
      self.parsechecker = parsechecker
      
      # This entire thing is hilariously grim.
      processedpattern = pattern.replace(" ", "\s*").replace("[", "").replace("]", "?").replace("<key>", "((?P<key>[^=]{1,255}?)\s*)").replace("<text>", "((?P<text>.+?)\s*)").replace("<command>", "((?P<command>\w+?)\s*)").replace("<version>", "((?P<version>-?\d{1,10})(\s+|$))").replace("<user>", "((?P<user>[^\s]{1,255})(\s+|$))").replace("<value>", "((?P<value>.*)(\s+|$))").replace("<hostmask>", "((?P<hostmask>[^\s]{1,255})(\s+|$))").replace("<level>", "((?P<level>[\w]+)(\s+|$))")
      processedpattern = "^\s*" + processedpattern + "$"
      print pattern
      print processedpattern
      
      self.regex = re.compile(processedpattern)
    
    def setConfused(self, confused):
      self.confused = confused
    
    def parsable(self, arguments, context):
      match = self.regex.match(arguments)
      if match == None:
        return False
      if self.parsechecker == None:
        return True
      
      context = copy.copy(context)
      # dupe code with dispatch
      for key,value in match.groupdict().iteritems():
        if key in context:
          raise Error
        elif value != None:
          context[key] = value
      
      return self.parsechecker(**context)
    
    def dispatch(self, arguments, context):
      result = self.regex.match(arguments)
      
      if result == None:
        raise "Fucked"
      
      context = copy.copy(context)
      # dupe code with parsable
      for key,value in result.groupdict().iteritems():
        if key in context:
          raise Error
        elif value != None:
          context[key] = value
      
      return self.function(**context)
    
  def __init__(self, channel, nickname, server, port=6667):
    self.lastnick = nickname
    SingleServerIRCBot.__init__(self, [(server, port)], nickname, nickname)
    self.channel = channel.split(':')[0]
    if len(channel.split(':')) > 1:
      self.channelkey = channel.split(':')[1]
    else:
      self.channelkey = ""
    self.nextspeak = itime()
    self.lastsaid = []
    self.lasttargeted = {}
    self.curtargets = {}
    self.timerRunning = 0
    self.compositeBuffer = {}
    self.compositeTiming = {}
    self.intendedNickname = nickname
    
    self.lookuptable = {
        "calc": self.ParseModule("USER", "<key>", self.command_calc, helptext = "Prints out the requested calc message."),
        "apropos": self.ParseModule("USER", "<text>", self.command_apropos, helptext = "Searches both calc keys and values for the given text."),
        "aproposk": self.ParseModule("USER", "<text>", self.command_aproposk, helptext = "Searches calc keys for the given text."),
        "aproposv": self.ParseModule("USER", "<text>", self.command_aproposv, helptext = "Searches calc values for the given text."),
        "apropos2": self.ParseModule("USER", "[<text>]", self.command_apropos2, visible = False), # error only
        "status": self.ParseModule("USER", "[<key>]", self.command_status, helptext = "Shows bot status with no parameter, or calc information with a calc key.", confused_help = False),
        "help": self.ParseModule("USER", "[<command>]", self.command_help, helptext = "Irrevocably destroys the universe. Never use this.", confused_help = False),
        "more": self.ParseModule("USER", "", self.command_more, helptext = "Gives more output from commands that can generate more than a page.", confused_help = False),
        "version": self.ParseModule("USER", "<version> <key>", self.command_version, helptext = "Shows old versions of calcs.", confused_help = False),
        "owncalc": self.ParseModule("USER", "<key>", self.command_owncalc, helptext = "Tells you who last changed a calc."),
        
        "tell": self.ParseModule("PUBLIC", "<user> <key>", self.command_tell, helptext = "Sends a calc directly to a user in private msg.", parsechecker = self.command_tell_parsechecker, confused_help = False),
        
        "mkcalc": self.ParseModule("CHANGE", "<key> = <value>", self.command_mkcalc, helptext = "Creates a new calc."),
        "rmcalc": self.ParseModule("CHANGE", "<key>", self.command_rmcalc, helptext = "Removes an existing calc."),
        "chcalc": self.ParseModule("CHANGE", "<key> = <value>", self.command_chcalc, helptext = "Changes an existing calc."),
        
        "whois": self.ParseModule("GOD", "[<user>]", self.command_whois, helptext = "Shows hostmask info for a user.", private_only = True),
        "match": self.ParseModule("GOD", "<hostmask>", self.command_match, helptext = "Matches a given hostmask to a user ID.", private_only = True),
        "addhost": self.ParseModule("GOD", "<user> <hostmask>", self.command_addhost, helptext = "Adds a host for a user.", private_only = True),
        "rmhost": self.ParseModule("GOD", "[<user>] <hostmask>", self.command_rmhost, helptext = "Removes a host from a user (defaults to removing hosts from yourself.)", private_only = True),
        "chperm": self.ParseModule("GOD", "<user> <level>", self.command_chperm, helptext = "Changes permission level for someone. IGNORE = bot does not pay attention to the user. USER = normal private-only access. PUBLIC = can calc in public and send tells. CHANGE = can change, add, or remove calcs. AUTHORIZE = same as CHANGE, kind of obsolete. GOD = can change permission levels and add hostmasks.", private_only = True),
      }
    
    for value in self.lookuptable.itervalues():
      value.setConfused(self.command_confused)
    
  class NotifySender:
    def __init__(self, text):
      self.text = text
    
    def dispatch(self, bot, user_nick, **kwargs):
      bot.queueMessage(('notice', user_nick), self.text)
  
  class MsgTarget:
    def __init__(self, text, cull = False):
      self.text = text
      self.cull = cull
    
    def dispatch(self, bot, target, **kwargs):
      bot.queueMessage(('privmsg', target), self.text, cull = self.cull)
  
  class MsgOther:
    def __init__(self, person, text):
      self.person = person
      self.text = text
    
    def dispatch(self, bot, **kwargs):
      bot.queueMessage(('privmsg', self.person), self.text)
  
  class CompositeTargetStart:
    def __init__(self, data, prefix):
      self.data = data
      self.prefix = prefix
    
    def dispatch(self, bot, user_nick, target, **kwargs):
      bot.queueCompositeMessage(user_nick, self.data, self.prefix)
      bot.queueCompositeMore(user_nick, ('privmsg', target))
  
  class CompositeTargetMore:
    def dispatch(self, bot, user_nick, target, **kwargs):
      bot.queueCompositeMore(user_nick, ('privmsg', target))
  
  def command_confused(self, target, **kwargs):
    if target[0] == '#':
      return [self.NotifySender("Confused? \"/msg %s help <command>\" for docs." % self.connection.get_nickname())]
    else:
      return [self.MsgTarget("Confused? \"help <command>\" for docs.")]
  
  def command_msgnotify(self, **kwargs):
    return [self.NotifySender("Sorry, you don't have permission to do that publicly. Op/voice yourself or send me a message.")]
  
  def command_noauth(self, target, **kwargs):
    if target[0] == '#':
      return [self.NotifySender("You don't have the permissions needed to do that.")]
    else:
      return [self.MsgTarget("You don't have the permissions needed to do that.")]
  
  def command_calc(self, key, **kwargs):
    global g_queryCount
    g_queryCount = g_queryCount + 1
    data = getEntry(key)
    incrementCount(key)
    if data == "":
      return [self.MsgTarget("No entry for \"%s\"" % key, cull = True)]
    else:
      return [self.MsgTarget("%s = %s" % (key, data), cull = True)]
  
  def command_apropos(self, text, **kwargs):
    return [self.CompositeTargetStart(apropos(text, key=True, value=True), "found: ")]
  
  def command_aproposk(self, text, **kwargs):
    return [self.CompositeTargetStart(apropos(text, key=True), "found: ")]
  
  def command_aproposv(self, text, **kwargs):
    return [self.CompositeTargetStart(apropos(text, value=True), "found: ")]
  
  def command_apropos2(self, **kwargs):
    return [self.NotifySender("apropos2 no longer exists. Try aproposk, aproposv, and apropos for searching keys, values, and everything, respectively.")]
  
  def command_status(self, key = None, **kwargs):
    if key == None:
      global g_changeCount, g_queryCount, g_startDate
      return [self.MsgTarget("I have %s entries in my database. There have been %s changes and %s queries since %s." % (getCalcCount(), g_changeCount, g_queryCount, g_startDate))]
    else:
      ver = getLastVersion(key)
      count = getCount(key)
      if count != 1:
        plural = "s"
      else:
        plural = ""
        
      if ver == None:
        return [self.MsgTarget("\"%s\" has been queried %s time%s and has no version history." % (key, count, plural))]
      else:
        return [self.MsgTarget("\"%s\" has been queried %s time%s and its last version is %s." % (key, count, plural, ver))]
  
  def command_help(self, lookuptable, permission, target, command = None, **kwargs):
    if target[0] == '#':
      return [self.NotifySender("Help can only be used in /msg.")]
    
    if command == None:
      options = "Available commands for level %s:" % permission
      permissionstraverse = [ "USER", "PUBLIC", "CHANGE", "GOD" ]
      for item in permissionstraverse:
        if adequatePermission(item, permission):
          for key, value in lookuptable.iteritems():
            if value.permission == item and value.visible:
              options = options + " " + key
      return [self.MsgTarget(options)]
    else:
      if not command in lookuptable or not lookuptable[command].visible:
        return [self.MsgTarget("\"%s\" is not a valid command." % command)]
      return [self.MsgTarget("%s Usage: %s %s" % (lookuptable[command].helptext, command, lookuptable[command].pattern))]
  
  def command_more(self, **kwargs):
    return [self.CompositeTargetMore()]
  
  def command_version(self, key, version, permission, target, **kwargs):
    entrytext, userid, userhost, time = getVersionedEntry(key, version)
    if entrytext == None:
      return [self.MsgTarget("\"%s\" v%s does not exist." % (key, version))]
    
    rv = []
    if permission != "GOD" or target[0] == '#':
      rv.append(self.MsgTarget("\"%s\" v%s changed at %s by %s" % (key, version, time, userid)))
    else:
      rv.append(self.MsgTarget("\"%s\" v%s changed at %s by %s (%s)" % (key, version, time, userid, userhost)))
    
    if entrytext == "":
      rv.append(self.MsgTarget("\"%s\" was deleted." % key))
    else:
      rv.append(self.MsgTarget("\"%s\" v%s = %s" % (key, version, entrytext)))
    
    return rv
  
  def command_owncalc(self, key, **kwargs):
    data = getEntry(key)
    if data == "":
      return [self.MsgTarget("\"%s\" does not exist." % key)]
    return [self.MsgTarget("\"%s\" was last edited by %s." % (key, getVersionedEntry(key, getLastVersion(key))[1]))]
  
  def command_tell_parsechecker(self, target, user, channel, **kwargs):
    if target[0] == '#' and not channel.has_user(user):
      return False
    return True
  
  def command_tell(self, user, key, target, user_nick, channel, **kwargs):
    if target[0] == '#' and not channel.has_user(user):
      return []   # We pretend nothing happened if the user doesn't exist in the channel and it wasn't in /msg
    
    global g_queryCount
    g_queryCount = g_queryCount + 1
    data = getEntry(key)
    realkey = key
    if data == "":
      splice = key.split(' ', 1)
      if len(splice) > 1:
        data = getEntry(splice[1])
        realkey = splice[1]
    
    incrementCount(key)
    
    if target[0] == '#':
      ResponseClass = self.NotifySender
    else:
      ResponseClass = self.MsgTarget
    
    if data == "" and target[0] == '#':
      return [ResponseClass("No entry for \"%s\"." % key)]
    elif data == "" and target[0] != '#':
      return [ResponseClass("No entry for \"%s\"." % key)]
    else:
      return [self.MsgOther(user, "%s wanted me to tell you:" % user_nick), self.MsgOther(user, "%s = %s" % (realkey, data)), ResponseClass("Calc %s sent to %s" % (realkey, user))]
  
  def command_mkcalc(self, key, value, user_host, user_id, **kwargs):
    global g_changeCount
    olddata = getEntry(key)
    if olddata != "":
      return [self.MsgTarget("I already have an entry for \"%s\"." % key)]
    if value == "":
      return [self.MsgTarget("Calc values need to be longer than zero bytes.")]
    g_changeCount = g_changeCount + 1
    changeEntry(key, value, user_host, user_id)
    return [self.MsgTarget("\"%s\" added." % key)]
  
  def command_rmcalc(self, key, user_host, user_id, **kwargs):
    global g_changeCount
    olddata = getEntry(key)
    if olddata == "":
      return [self.MsgTarget("\"%s\" is not a valid calc." % key)]
    g_changeCount = g_changeCount + 1
    changeEntry(key, "", user_host, user_id)
    return [self.MsgTarget("\"%s\" removed." % key)]
  
  def command_chcalc(self, key, value, user_host, user_id, **kwargs):
    global g_changeCount
    olddata = getEntry(key)
    if olddata == value:
      return [self.MsgTarget("\"%s\" is already equal to that." % key)]
    g_changeCount = g_changeCount + 1
    changeEntry(key, value, user_host, user_id)
    return [self.MsgTarget("\"%s\" changed." % key)]
  
  def command_whois(self, user_host, user = None, **kwargs):
    if user == None:
      user = getMatch(user_host)
    if user == "":
      return [self.MsgTarget("I can't figure out who you are. You'll have to give an explicit target.")]
    return [self.CompositeTargetStart(showhost(user), "%s (%s): " % (user, getNickPermissions(user)))]
  
  def command_match(self, hostmask, **kwargs):
    matches = getMatch(hostmask)
    if matches == "":
      return [self.MsgTarget("No matches.")]
    else:
      return [self.MsgTarget("Matches user %s." % matches)]
  
  def command_addhost(self, hostmask, user_host, user = None, **kwargs):
    if user == None:
      user = getMatch(user_host)
    if user == "":
      return [self.MsgTarget("I can't figure out who you are. You'll have to give an explicit target.")]
    
    if not addhost(user, hostmask, user_host):
      return [self.MsgTarget("That host already exists for \"%s\"" % user)]
    else:
      return [self.MsgTarget("Host added for \"%s\"" % user)]
  
  def command_rmhost(self, hostmask, user_host, user = None, **kwargs):
    if user == None:
      user = getMatch(user_host)
    if user == "":
      return [self.MsgTarget("I can't figure out who you are. You'll have to give an explicit target.")]
    
    if not rmhost(user, hostmask, user_host):
      return [self.MsgTarget("That host does not exist on \"%s\"" % user)]
    else:
      return [self.MsgTarget("Host removed for \"%s\"" % user)]
  
  def command_chperm(self, user, level, user_host, permission, **kwargs):
    if not chperm(user, level, user_host):
      return [self.MsgTarget("Invalid permission level")]
    else:
      return [self.MsgTarget("%s set to permission level %s" % (user, level))]
  
  def updateLastsaid(self):
    #print self.lastsaid
    while len(self.lastsaid) and self.lastsaid[0][0] < itime() - 10:
      self.lastsaid = self.lastsaid[1:]
    #print self.lastsaid
    
  def queueMessage(self, target, data, cull = False):
    #print "queueing ", target, data
    self.updateLastsaid()
    if not self.curtargets.has_key(target):
      self.curtargets[target] = []
    if not self.lasttargeted.has_key(target):
      self.lasttargeted[target] = 0
    if cull:
      for time, value in self.lastsaid:
        if value == (target, data):
          if len(self.curtargets[target]) == 0:
            del self.curtargets[target]
          return
    #print self.lastsaid
    #print self.curtargets
    #print self.timerRunning
    #print self.lastspoken
    #print itime()
    if not cull or not self.curtargets[target].count(data):
      self.curtargets[target].append(data)
      if not self.timerRunning and self.nextspeak <= itime():
        self.timerRunning = 1
        self.dequeueMessage()
      elif not self.timerRunning:
        self.timerRunning = 1
        self.ircobj.execute_delayed(1, self.dequeueMessage, ())
    elif len(self.curtargets[target]) == 0:
      del self.curtargets[target]
      
  def dequeueMessage(self):
    #print "entering deque"
    if self.nextspeak > itime():
      self.ircobj.execute_delayed(1, self.dequeueMessage, ())
      return
    self.updateLastsaid()
    while 1:
      target = ("","")
      besttime = itime() + 60
      for key in self.curtargets.iterkeys():
        if self.lasttargeted[key] < besttime:
          besttime = self.lasttargeted[key]
          target = key
      if target == ("",""):
        raise Error, "Queue fucked"
      data = self.curtargets[target][0]
      #print "snagorated ", target, data
      print (target, data)
      if len(self.curtargets[target]) == 1:
        del self.curtargets[target]
      else:
        self.curtargets[target] = self.curtargets[target][1:]
      self.lastsaid.append((itime(),(target,data)))
      self.lasttargeted[target] = itime()
      if target[0] == 'notice':
        self.connection.notice(target[1], data)
      elif target[0] == 'privmsg':
        self.connection.privmsg(target[1], data)
      else:
        raise Error
      self.nextspeak = max(self.nextspeak + 2, itime() - 6 + 2)
      if len(self.curtargets):
        self.dequeueMessage()
        #self.ircobj.execute_delayed(1, self.dequeueMessage, ())
      else:
        self.timerRunning = 0
      return
    
  def recheckNickname(self):
    print "Rechecking nickname"
    if self.connection.get_nickname() != self.intendedNickname:
      self.connection.nick(self.intendedNickname)

  def recheckIdle(self):
    if self.lastcommand < itime() - 15 * 60:
      print "disconnecting due to idle-timeout"
      self.connection.disconnect("If this happens, please let ZorbaTHut know.")
    else:
      self.ircobj.execute_delayed(15, self.recheckIdle, ())

  def on_nicknameinuse(self, c, e):
    if len(self.channels) == 0:
      if self.lastnick == "CalcMe":
        self.lastnick = "CalcBot"
      else:
        self.lastnick = self.lastnick + "_"
      print "Changing nick to " + self.lastnick
      c.nick(self.lastnick)
    else:
      self.ircobj.execute_delayed(5, self.recheckNickname, ())

  def on_welcome(self, c, e):
    global g_startDate
    g_startDate = time.asctime()
    c.join(self.channel, self.channelkey)
    if c.get_nickname() != self.intendedNickname:
      self.ircobj.execute_delayed(5, self.recheckNickname, ())
    self.lastcommand = itime()
    self.ircobj.execute_delayed(15, self.recheckIdle, ())

  def on_privmsg(self, c, e):
    self.antiidle()
    self.do_command(e)

  def on_pubmsg(self, c, e):
    self.antiidle()
    self.do_command(e)
    
  def on_kick(self, c, e):
    self.antiidle()
    c.join(self.channel, self.channelkey)
  
  def on_join(self, c, e):
    print "join"
    self.antiidle()

  def on_part(self, c, e):
    print "part"
    self.antiidle()

  def on_quit(self, c, e):
    print "quit"
    self.antiidle()    

  def on_mode(self, c, e):
    print "mode"
    self.antiidle()    

  def on_ping(self, c, e):
    print "ping"
    self.antiidle()    

  def on_privnotice(self, c, e):
    print "privnotice"
    self.antiidle()

  def on_pubnotice(self, c, e):
    print "pubnotice"
    self.antiidle()

  def on_disconnect(self, c, e):
    print "Disconnected, dying"
    self.ircobj.execute_delayed(15, self.die, ())

  def die(self):
    sys.exit(1)

  def antiidle(self):
    self.lastcommand = itime()
    
  def on_bannedfromchan(self, c, e):
    print "Banned, sleeping"
    time.sleep(10)
    print "Retrying"
    c.join(self.channel, self.channelkey)
    
  def doCompositeCulling(self):
    if len(self.compositeBuffer) < 100:
      return
    todelete = []
    for key in self.compositeBuffer.iterkeys():
      if self.compositeTiming[key] + 60 * 15 < itime():
        todelete.append(key)
    print "COMPOSITEDELETE", todelete
    for key in todelete:
      del self.compositeBuffer[key]
    
  def queueCompositeMessage(self, nick, values, prefix):
    if nick in self.compositeBuffer:
      del self.compositeBuffer[nick]
    self.doCompositeCulling()
    self.compositeBuffer[nick] = []
    self.compositeTiming[nick] = itime()
    if len(values) == 0:
      self.compositeBuffer[nick].append(prefix + "no matches")
    while len(values):
      output = prefix
      while len(values) and len(output) + len(values[0]) + 4 < 400:
        output = output + ('"%s" ' % values[0])
        values = values[1:]
      if len(values):
        output = output + "..."
      self.compositeBuffer[nick].append(output)
    #print self.compositeBuffer[nick]
  
  def queueCompositeMore(self, nick, target):
    if nick in self.compositeBuffer:
      self.queueMessage(target, self.compositeBuffer[nick][0])
      self.compositeBuffer[nick] = self.compositeBuffer[nick][1:]
      self.compositeTiming[nick] = itime()
      if len(self.compositeBuffer[nick]) == 0:
        del self.compositeBuffer[nick]
    else:
      self.queueMessage(target, "Nothing left to display.")
    
  def do_command(self, e):
    global g_startDate, g_changeCount, g_queryCount, g_lastuser, g_lastcommand
    g_lastuser = e.source()
    g_lastcommand = e.arguments()[0]
    #print e.eventtype()
    #print e.source()
    #print e.target()
    #print e.arguments()
    
    if e.eventtype() != "pubmsg" and e.eventtype() != "privmsg":
      connection.privmsg("ZorbaTHut", "Unknown message type: %s" % (e.eventtype()))
      print "Unknown message type", e.eventtype() # TODO: /msg Zorba
    
    # Remove control characters
    sanitized = re.sub('[\x00-\x1f]','',e.arguments()[0])
    
    if len(sanitized.split(' ', 1)) == 1:
      command = sanitized
      arguments = ""
    else:
      command, arguments = sanitized.split(' ', 1)
    
    arguments = arguments.strip()
    
    user_host = e.source()
    user_nick = nm_to_n(user_host)
    
    if e.eventtype() == "privmsg":
      target = user_nick
    else:
      target = e.target()
    
    if not self.lookuptable.has_key(command) and target[0] == "#":
      return
    
    permission, user_id = getPermissions(user_host, self.channels[self.channel])
    
    print command, arguments, target, user_host, user_nick, permission, user_id
    
    if permission == "IGNORE":
      return
      
    context = { "target": target, "user_host": user_host, "user_nick": user_nick, "permission": permission, "user_id": user_id, "lookuptable": self.lookuptable, "channel": self.channels[self.channel] }
    
    if not self.lookuptable.has_key(command):
      result = self.command_confused(**context)
    elif target[0] == "#" and self.lookuptable[command].private_only:
      return
    else:
      silent = not self.lookuptable[command].confused_help
      if target[0] != "#":
        silent = False
      parseable = self.lookuptable[command].parsable(arguments, context)
      
      if target[0] == "#" and permission == "USER" and adequatePermission(self.lookuptable[command].permission, permission):  # If they would have permission otherwise, but they're a user and it's in public . . .
        adequateperms = False
        autherror = self.command_msgnotify
      else:
        adequateperms = adequatePermission(self.lookuptable[command].permission, permission)
        autherror = self.command_noauth
      
      if not silent:
        if not adequateperms:
          result = autherror(**context)
        elif not parseable:
          result = self.command_confused(**context)
        else:
          result = self.lookuptable[command].dispatch(arguments, context)
      else:
        if not parseable:
          result = []
        elif not adequateperms:
          result = autherror(**context)
        else:
          result = self.lookuptable[command].dispatch(arguments, context)
    
    print result
    
    for item in result:
      item.dispatch(self, **context)
    
    return

def main():
  import sys
  print len(sys.argv)
  if len(sys.argv) == 1:
    print "Usages: testbot run dbhost dbname dbusername dbpassword <server[:port]> <channel> <nickname>"
    print "    testbot load dbhost dbname dbusername dbpassword <filename>"
    print "    testbot replay dbhost dbname dbusername dbpassword <filename>"
    sys.exit(1)
    
  global g_username, g_passwd, g_dbhost, g_dbname
  g_dbhost = sys.argv[2]
  g_dbname = sys.argv[3]
  g_username = sys.argv[4]
  g_passwd = sys.argv[5]
  initDb()
  
  if sys.argv[1] == "run":
    if len(sys.argv) != 9:
      sys.exit(1)
  
    s = string.split(sys.argv[6], ":", 1)
    server = s[0]
    if len(s) == 2:
      try:
        port = int(s[1])
      except ValueError:
        print "Error: Erroneous port."
        sys.exit(1)
    else:
      port = 6667
    channel = sys.argv[7]
    nickname = sys.argv[8]
  
    bot = TestBot(channel, nickname, server, port)
    
    try:
      bot.start()
    except KeyboardInterrupt:
      raise
    except Exception:
      exci = traceback.extract_tb(sys.exc_info()[2])[-1]
      print exci
      bot.connection.privmsg("ZorbaTHut", "%s:%s (%s) - %s: %s" % (exci[0], exci[1], exci[2], g_lastuser, g_lastcommand))
      raise
  #################
  # Pretty much all the code beneath this line is dead - it was designed to be run once, and I ran it, and it worked, and now it's not being run again. May take some tweaking to make it work again - it's mostly being left in in case it's ever needed again.
  #################
  elif sys.argv[1] == "load":
    if len(sys.argv) != 6:
      print "Missing filename"
    input = open(sys.argv[5])
    for x in input:
      tok = x.split("::", 3)
      if tok == ["\n"]:
        break
      tok[3] = tok[3].strip()   # this line hasn't been tested, so if it crashes here, fix it - it should remove whitespace so we don't pollute the DB with trailing \r\n pairs
      print "Adding %s: %s" % (tok[1], tok[3])
      changeEntry(tok[1], tok[3], tok[0] + " (factoid.db)")
      setCount(tok[1], int(tok[2]))
  elif sys.argv[1] == "loadusers":
    if len(sys.argv) != 6:
      print "Missing filename"
    input = open(sys.argv[5])
    for x in input:
      print "got " + x
      if x[0] == '#' or x[0] == '\r' or x[0] == '\n':
        continue
      tok = toki(x)
      if len(tok) != 3:
        raise Error, "Bort"
      tok[0] = tok[0].lower()
      for mask in tok[1].split(','):
        print "adding", mask, "for", tok[0]
        addhost(tok[0], mask, "loadusers")
      if tok[-1] == "f":
        newperm = "PUBLIC"
      elif tok[-1] == "o":
        newperm = "CHANGE"
      elif tok[-1] == "m" or tok[-1] == "+m":
        newperm = "AUTHORIZE"
      elif tok[-1] == "n":
        newperm = "GOD"
      elif tok[-1] == "x":
        newperm = "USER"
      else:
        raise Error, "Dang"
      chperm(tok[0], newperm, "loadusers")
    chperm("zorbathut", "GOD", "loadusers")
  elif sys.argv[1] == "replay":
    if len(sys.argv) != 6:
      print "Missing filename"
    class DemoItem:
      def __init__(self, user, text):
        self.user = user
        self.text=text
      
      def source(self):
        return self.user
    
      def arguments(self):
        return [self.text]
      
      def eventtype(self):
        return "pubmsg"
    
      def target(self):
        return "#c++"
    
    class DemoChannel:
      def is_oper(self, nick):
        return True
    
      def is_voiced(self, nick):
        return True
    
    def echo_privmsg(target, data):
      print target + ": " + data
    
    bot = TestBot("", "CalcBot", "", 0)
    bot.channel = 0
    bot.channels = [DemoChannel()]
    bot.connection.privmsg = echo_privmsg
    
    fil = open(sys.argv[5], "r")
    ct = 0
    for line in fil:
      if ct == 10000:
        print fil.tell() / 144022069.0
        ct = 0
      ct = ct + 1
      if line == "":
        continue
      if line[0] == '\r' or line[0] == '\n':
        continue
      if line[0:4] == "****":
        continue
      match = re.match(".{3} [0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} ([^\t]*)\t(.*)", line)
      if match == None:
        print "FAILURE: " + line
        continue
      if match.group(1) == "*":
        continue
      if match.group(1) == "CalcMe":
        ubermatch = re.match("([^ ]* ?[^ ]*) = (.*)", match.group(2))
        if ubermatch == None:
          #print "Calcme failure: " + match.group(2)
          continue
        #print ubermatch.group(1)
        #print ubermatch.group(2)
        bot.do_command(DemoItem("unknown (channel log intercept)", "chcalc %s = %s" % (ubermatch.group(1), ubermatch.group(2))))
      else:
        #print match.group(1)
        #print match.group(2)
        bot.do_command(DemoItem(match.group(1) + " (channel log replay)", match.group(2)))
    fil.close()
    
  else:
    print "Error"
    sys.exit(1)
    

if __name__ == "__main__":
  try:
    main()
  except KeyboardInterrupt:
    print "Interrupted, shutting down"
    sys.exit(0)
  except Exception:
    exci = traceback.format_exc()
    print exci
    print g_lastuser
    dumpCrashlog(g_lastuser, exci, g_lastcommand)
