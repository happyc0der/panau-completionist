"""The "earned" unlock: overlay, cheats and wingsuit become available once your newest save shows the story finished
(mercenary mode: the last Agency mission, km07, completed) on Hardcore, the hardest difficulty.
config unlock = "always" skips the check."""
from panau import config, steam
from panau.save import progress


def status():
    """(unlocked, explanation)"""
    mode = config.load()['unlock']
    if mode == 'always':
        return True, 'unlock = "always" in the config'
    try:
        path = steam.newest_save()
        s = progress.load_summary(path)
    except (steam.NotFound, OSError, ValueError) as e:
        return False, f'could not read your save ({e})'
    if s['story_finished'] and s['difficulty'] == progress.HARDEST:
        return True, 'earned: story finished on Hardcore'
    need = []
    if not s['story_finished']:
        need.append('finish the story (the last Agency mission starts mercenary mode)')
    if s['difficulty'] != progress.HARDEST:
        need.append(f'play on Hardcore (this save is {s["difficulty_name"]})')
    return False, 'locked: ' + ' and '.join(need) + '. Or set unlock = "always": panau config unlock always'


def require():
    ok, why = status()
    if not ok:
        print(why)
    return ok
