"""High-level facts about a save: difficulty, story finished, completion counts."""
import struct

from panau.hashing import hashlittle
from panau.save.format import Save

DIFFICULTIES = {0: 'Casual', 1: 'Normal', 2: 'Experienced', 3: 'Hardcore'}
HARDEST = 3
# the seven story ("Agency") missions are activities km01..km07; finishing km07 starts mercenary mode
FINAL_MISSION = struct.pack('<I', hashlittle(b'km07'))
COMPLETED = 0x04


def activity_status(save, activity_id):
    rows = save['activities']
    for n, (_, d) in enumerate(rows):
        if d == activity_id and n + 1 < len(rows) and len(rows[n + 1][1]) == 1:
            return rows[n + 1][1][0]
    return None


def story_finished(save):
    status = activity_status(save, FINAL_MISSION)
    return status is not None and bool(status & COMPLETED)


# faction items: 100 each of skulls (csk), black boxes (cbb) and drug drops (cdd). Each is a one-item activity
# <kind>00..99, completed once picked up (a completed one no longer spawns). The game shows their counters, stats
# 333-335, and the total in 336 and 370; it never recounts them from the activity list.
FACTION_ITEMS = {'csk': 333, 'cbb': 334, 'cdd': 335}
FACTION_TOTALS = (336, 370)


def faction_items(save):
    """{kind: number picked up}, from the activity list."""
    return {k: sum(bool((activity_status(save, struct.pack('<I', hashlittle(f'{k}{n:02d}'.encode()))) or 0) & COMPLETED)
                   for n in range(100)) for k in FACTION_ITEMS}


def summary(save):
    return {
        'difficulty': save.difficulty,
        'difficulty_name': DIFFICULTIES.get(save.difficulty, str(save.difficulty)),
        'story_finished': story_finished(save),
        'collected': len(save['collected']) - 1,
    }


def load_summary(path):
    return summary(Save.load(path))
