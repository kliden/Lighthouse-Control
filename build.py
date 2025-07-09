import PyInstaller.__main__ as main

main.run([
    'lighthouse/lighthouse.py',
    '--onefile',
    '--name=lighthouse',
    '--noconsole',
    '--icon=icons/lighthouse_on.ico'
])

main.run([
    'lighthouse/lighthouse.py',
    '--onefile',
    '--name=lighthouse_console',
    '--icon=icons/lighthouse_off.ico'
])