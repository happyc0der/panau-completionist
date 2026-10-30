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


def summary(save):
    return {
        'difficulty': save.difficulty,
        'difficulty_name': DIFFICULTIES.get(save.difficulty, str(save.difficulty)),
        'story_finished': story_finished(save),
        'collected': len(save['collected']) - 1,
    }


def load_summary(path):
    return summary(Save.load(path))
