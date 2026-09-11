from pathlib import Path
p=Path('bot.py')
s=p.read_text()
# Persistent memory is installed by the main bot patch; this file is only a marker for deployment automation.
print('persistent-memory patch marker')
