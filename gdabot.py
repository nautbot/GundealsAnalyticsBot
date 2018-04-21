import subprocess, traceback

while True:
    try:
        p = subprocess.call(['python3', 'gdabotloop.py'])
    except (SyntaxError, FileNotFoundError):
        p = subprocess.call(['python', 'gdabotloop.py'])
    except:
        traceback.print_exc()
        pass