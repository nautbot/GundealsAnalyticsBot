import datetime, time, json, sqlite3, praw, re
from enum import Enum


with open('config_praw.json') as settingsPrawRaw:
    settingsPraw = json.load(settingsPrawRaw)

with open('config_bot.json') as settingsBotRaw:
    settingsBot = json.load(settingsBotRaw)
    

# Console reporting commands
def logAppEvent(message, e=None):
    if not e is None:
        print("{} - {}: ".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message), e)
    else:
        print("{} - {}".format(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))


# Application info
startTime = int(time.time())
lastModUpdate = 0
botVersion = "0.1.0"
username = settingsPraw["username"]
logAppEvent("{} - version {}".format(username, botVersion))


sql = sqlite3.connect('sql.db')
logAppEvent('Loaded SQL Database')
cur = sql.cursor()
cur.execute('CREATE TABLE IF NOT EXISTS submissions(id TEXT, user TEXT, shortlink TEXT, title TEXT, dealurl TEXT, sqltime TIMESTAMP)')
logAppEvent('Loaded Submissions')
cur.execute('CREATE TABLE IF NOT EXISTS votes(submissionid TEXT, commentid TEXT, user TEXT, vote INTEGER, sqltime TIMESTAMP)')
logAppEvent('Loaded Votes')
sql.commit()


r = praw.Reddit(
    client_id=settingsPraw["client_id"],
    client_secret=settingsPraw["client_secret"],
    redirect=settingsPraw["redirect"],
    username=settingsPraw["username"],
    password=settingsPraw["password"],
    user_agent="python:com.nauticalmile.{}:v{} (by /u/nauticalmile)".format(username, botVersion)
)


logAppEvent("Logged in to reddit as: python:com.{}:v{} (by /u/nauticalmile)".format(username, botVersion))


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


def collectCommentVotes(comment, submissionid):
    try:
        if not comment in processedComments and comment.author is not None and comment.author.name != username:
            cur.execute('SELECT commentid FROM votes WHERE submissionid=? and user=?', (submissionid, comment.author.name))
            if not cur.fetchone():
                commentVote = findCommentVote(comment)
                if not commentVote == None:
                    cur.execute('INSERT INTO votes VALUES(?,?,?,?,?)', (submissionid, comment.id, comment.author.name, commentVote.value, comment.created_utc))
                    sql.commit()
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
        urls = re.findall('https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', submission.selftext)
        for f in settingsBot['submissionParsing']['urlFilters']:
            for url in urls:
                if f in url: return url
        return ''
    except Exception as e:
        logAppEvent('findSubmissionLinkURL : ', e)
        pass


def collectSubmissionVotes(submission):
    try:
        if not submission in processedSubmissions and submission.author is not None and submission.author.name != username:
            cur.execute('SELECT id FROM submissions WHERE id=?', (submission.id,))
            if not cur.fetchone():
                dealurl = findSubmissionLinkURL(submission)
                cur.execute('INSERT INTO submissions VALUES(?,?,?,?,?,?)', (submission.id, submission.author.name, submission.shortlink, submission.title, dealurl, submission.created_utc))
                sql.commit()
            cur.execute('SELECT submissionid FROM votes WHERE submissionid=? and user=?', (submission.id, submission.author.name))
            if not cur.fetchone():
                submissionVote = findSubmissionVote(submission)
                if not submissionVote == None:
                    cur.execute('INSERT INTO votes VALUES(?,?,?,?,?)', (submission.id, '', submission.author.name, submissionVote.value, submission.created_utc))
                    sql.commit()
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
        cur.execute('SELECT count(*) FROM votes WHERE submissionid=? and vote=?', (submissionid, voteType.value))
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
        summaryBody = """#### **User Experience Summary:**
\n\n Positive : {}
\n\n Neutral : {}
\n\n Negative : {}
\n\n -----
\n\n Tell us your experience with this deal or vendor!  Include [Positive], [Neutral] or [Negative] in your comment!
\n\n [^*What* ^*is* ^*this?*](https://www.reddit.com/r/GunDeals_Reviews/wiki/gdanalbot) ^| ^(*Last updated at: {} UTC*)""".format(positiveVotes, neutralVotes, negativeVotes, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        comments = submission.comments
        for comment in comments:
            if comment.author == r.redditor(username) and comment.is_root:
                comment.edit(summaryBody)
                return
        reply = submission.reply(summaryBody)
        reply.mod.distinguish(how='yes', sticky=True)
    except Exception as e:
        logAppEvent('updateSubmissionVoteSummary : ', e)
        pass


def scanSubmissions():
    try:
        for submission in r.subreddit(settingsBot['subreddit']).new(limit=100):
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
        time.sleep(10)
        if int(time.time()) - startTime > 604800: break
    except Exception as e:
        logAppEvent('main :', e)
        pass
