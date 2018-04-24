import datetime
from enum import Enum
import json
import time
import re

import praw
import sqlite3


with open('config_praw.json') as settingsPrawRaw:
    settingsPraw = json.load(settingsPrawRaw)

with open('config_bot.json') as settingsBotRaw:
    settingsBot = json.load(settingsBotRaw)
    

def getTimestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# Console reporting commands
def logAppEvent(message, e=None):
    if not e is None:
        print("{} - {}: ".format(getTimestamp(), message), e)
    else:
        print("{} - {}".format(getTimestamp(), message))


# Application info
firstRun = True
startTime = int(time.time())
lastModUpdate = 0
username = settingsPraw["username"]


sql = sqlite3.connect('sql.db')
logAppEvent('Loaded SQL Database')
cur = sql.cursor()
# Create submissions table
cur.execute('CREATE TABLE IF NOT EXISTS '
            'submissions(id TEXT, user TEXT, '
            'shortlink TEXT, title TEXT, dealurl TEXT, '
            'updatetime TIMESTAMP, sqltime TIMESTAMP)')
logAppEvent('Loaded Submissions')
# Create votes table
cur.execute('CREATE TABLE IF NOT EXISTS '
            'votes(submissionid TEXT, '
            'commentid TEXT, user TEXT, vote INTEGER, sqltime TIMESTAMP)')
logAppEvent('Loaded Votes')
sql.commit()


r = praw.Reddit(
    client_id=settingsPraw["clientID"],
    client_secret=settingsPraw["clientsecret"],
    redirect=settingsPraw["redirect"],
    username=settingsPraw["username"],
    password=settingsPraw["password"],
    user_agent=settingsPraw["useragent"]
)
logAppEvent("Logged in to reddit as: {}".format(settingsPraw["useragent"]))


class Vote(Enum):
    DEFAULT = 0
    POSITIVE = 1
    NEUTRAL = 2
    NEGATIVE = 3


processedComments = []
processedSubmissions = []


def findCommentVote(comment):
    try:
        commentBody = comment.body.lower()
        for trigger in settingsBot['commentVoting']['positiveVotes']:
            if trigger.lower() in commentBody:
                return Vote.POSITIVE
        for trigger in settingsBot['commentVoting']['neutralVotes']:
            if trigger.lower() in commentBody:
                return Vote.NEUTRAL
        for trigger in settingsBot['commentVoting']['negativeVotes']:
            if trigger.lower() in commentBody:
                return Vote.NEGATIVE
        return None
    except Exception as e:
        logAppEvent('findCommentVote : ', e)
        pass


def findSubmissionVote(submission):
    try:
        submissionTitle = submission.title.lower()
        for trigger in settingsBot['submissionVoting']['positiveVotes']:
            if trigger.lower() in submissionTitle:
                return Vote.POSITIVE
        for trigger in settingsBot['submissionVoting']['neutralVotes']:
            if trigger.lower() in submissionTitle:
                return Vote.NEUTRAL
        for trigger in settingsBot['submissionVoting']['negativeVotes']:
            if trigger.lower() in submissionTitle:
                return Vote.NEGATIVE
        return None
    except Exception as e:
        logAppEvent('findCommentVote : ', e)
        pass


def logSubmission(submission):
    try:
        # Check if submission entry exists
        cur.execute(('SELECT id FROM submissions '
                        'WHERE id=?'),
                        (submission.id,))
        # If entry doesn't exist, log submission
        if not cur.fetchone():
            dealurl = findSubmissionLinkURL(submission)
            cur.execute(('INSERT INTO submissions '
                            'VALUES(?,?,?,?,?,?,?)'),
                        (
                            submission.id,
                            submission.author.name,
                            submission.shortlink,
                            submission.title,
                            dealurl,
                            None,
                            submission.created_utc
                        ))
            sql.commit()
    except Exception as e:
        logAppEvent('logSubmission : ', e)
        pass


def logSubmissionVote(submission):
    try:
        if submission in processedSubmissions: return
        # Check if submission vote entry exists
        cur.execute(('SELECT submissionid FROM votes '
                    'WHERE submissionid=? and user=?'),
                    (
                        submission.id,
                        submission.author.name
                    ))
        # If entry doesn't exist, log submission vote entry
        if not cur.fetchone():
            submissionVote = findSubmissionVote(submission)
            if not submissionVote == None:
                cur.execute('INSERT INTO votes VALUES(?,?,?,?,?)',
                            (
                                submission.id,
                                None,
                                submission.author.name,
                                submissionVote.value,
                                submission.created_utc
                            ))
                sql.commit()
    except Exception as e:
        logAppEvent('logSubmissionVote : ', e)
        pass


def logCommentVote(comment, submissionid):
    try:
        if comment in processedComments: return
        # Check if comment vote entry exists
        cur.execute(('SELECT commentid FROM votes '
                    'WHERE submissionid=? and user=?'),
                    (
                        submissionid,
                        comment.author.name
                    ))
        if not cur.fetchone():
            # If entry doesn't exist, log comment vote
            commentVote = findCommentVote(comment)
            if not commentVote == None:
                cur.execute('INSERT INTO votes VALUES(?,?,?,?,?)',
                            (
                                submissionid,
                                comment.id,
                                comment.author.name,
                                commentVote.value,
                                comment.created_utc
                            ))
                sql.commit()
        else:
            # If entry exists, update to reflect new comment vote
            commentVote = findCommentVote(comment)
            if not commentVote == None:
                cur.execute(('UPDATE votes '
                            'SET commentid=?, vote=?, sqltime=? '
                            'WHERE submissionid=? and user=?'),
                            (
                                comment.id,
                                commentVote.value,
                                comment.created_utc,
                                submissionid,
                                comment.author.name
                            ))
                sql.commit()
    except Exception as e:
        logAppEvent('logSubmissionVote : ', e)
        pass


def collectCommentVotes(comment, submissionid):
    try:
        if (
                not comment in processedComments
                and comment.author is not None
                and comment.author.name != username
            ):
            comment.refresh()
            logCommentVote(comment, submissionid)
            processedComments.append(comment)
        replies = comment.replies
        while True:
            try:
                replies.replace_more()
                break
            except Exception as e:
                pass
        for reply in replies:
            collectCommentVotes(reply, submissionid)
    except Exception as e:
        logAppEvent('collectCommentVotes : ', e)
        pass


def findSubmissionLinkURL(submission):
    try:
        urls = re.findall('https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+',
                          submission.selftext)
        for f in settingsBot['submissionParsing']['urlFilters']:
            for url in urls:
                if f in url: return url
        return ''
    except Exception as e:
        logAppEvent('findSubmissionLinkURL : ', e)
        pass


def collectSubmissionVotes(submission):
    try:
        if (
                not submission in processedSubmissions
                and submission.author is not None
                and submission.author.name != username
            ):
            logSubmission(submission)
            logSubmissionVote(submission)
        processedSubmissions.append(submission)
        comments = submission.comments
        while True:
            try:
                comments.replace_more()
                break
            except Exception as e:
                pass
        for comment in comments:
            collectCommentVotes(comment, submission.id)
    except Exception as e:
        logAppEvent('collectSubmissionVotes : ', e)
        pass


def getVoteCount(submissionid, voteType):
    try:
        cur.execute('SELECT count(*) FROM votes ' \
                    'WHERE submissionid=? and vote=?',
                    (submissionid, voteType.value))
        voteCount = cur.fetchone()
        return int(voteCount[0])
    except Exception as e:
        logAppEvent('getVoteCount : ', e)
        pass


def updateSubmissionVoteSummary(submission):
    try:
        positiveVotes = getVoteCount(submission.id, Vote.POSITIVE)
        neutralVotes = getVoteCount(submission.id, Vote.NEUTRAL)
        negativeVotes = getVoteCount(submission.id, Vote.NEGATIVE)
        summaryBody = ('#### *What do others think of this deal/vendor?*'
                      '\n\nPositive|Neutral|Negative'
                      '\n:--:|:--:|:--:'
                      '\n{}|{}|{}'
                      '\n\n^(Tell us your experience! '
                      'Include [Positive], [Neutral] or [Negative] in your comment!)'
                      '\n\n [^*What* ^*is* ^*this?*]({}) ^| '
                      '^(*Last updated at: {} UTC*)') \
                      .format(
                                positiveVotes,
                                neutralVotes,
                                negativeVotes,
                                settingsBot['wikiDoc'],
                                getTimestamp()
                            )
        lastUpdate = None
        lastVote = None
        cur.execute('SELECT updatetime FROM submissions ' \
                    'WHERE id=? AND updatetime IS NOT NULL', 
                    (submission.id,))
        fetch = cur.fetchone()
        if fetch is not None:
            lastUpdate = int(fetch[0])
        cur.execute('SELECT sqltime FROM votes ' \
                    'WHERE submissionid=? ' \
                    'ORDER BY sqltime DESC LIMIT 1',
                    (submission.id,))
        fetch = cur.fetchone()
        if fetch is not None:
            lastVote = int(fetch[0])
        if firstRun or (lastVote is not None and (lastUpdate is None or lastVote > lastUpdate)):
            comments = submission.comments
            replyFound = False
            for comment in comments:
                if comment.author == r.redditor(username) and comment.is_root:
                    comment.edit(summaryBody)
                    replyFound = True
                    break
            if not replyFound:
                reply = submission.reply(summaryBody)
                reply.mod.distinguish(how='yes', sticky=True)
            cur.execute('UPDATE submissions ' \
                        'SET updatetime=? WHERE id=?',
                        (
                            int(time.time()),
                            submission.id
                        ))
            sql.commit()
    except Exception as e:
        logAppEvent('updateSubmissionVoteSummary : ', e)
        pass


def scanSubmissions():
    try:
        for submission in r.subreddit(settingsBot['subreddit']).new(limit=500):
            collectSubmissionVotes(submission)
            updateSubmissionVoteSummary(submission)
            time.sleep(2)
    except Exception as e:
        logAppEvent('scanSubmissions : ', e)
        pass


def scan():
    try:
        scanSubmissions()
    except Exception as e:
        logAppEvent('scan : ', e)
        pass


while True:
    try:
        scan()
        cur.execute("VACUUM")
        if firstRun: firstRun = False
        time.sleep(10)
    except Exception as e:
        logAppEvent('main :', e)
        pass
