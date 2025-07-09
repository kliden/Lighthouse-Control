import PyInstaller.__main__ as main

main.run([
    'lighthouse/lighthouse.py',
    '--onefile',
    '--name=lighthouse',
    '--noconsole'
])

main.run([
    'lighthouse/lighthouse.py',
    '--onefile',
    '--name=lighthouse_console'
])