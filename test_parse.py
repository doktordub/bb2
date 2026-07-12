
with open('docs/chart_test_prompts.md', 'r', encoding='utf-8') as f:
    text = f.read()

import re
# Find sections like:
# ## P01 - bar
# Expected artifact: ar
# Prompt:
# <prompt text>
# and stop at next ## or EOF

pattern = r'##\s*(P\d+)\s+-\s+([^\n]+)\s*\n\s*Expected artifact:\s*([^]+)\s*\n\s*Prompt:\s*\n(.*?)(?=\n##|$)'
matches = re.findall(pattern, text, re.DOTALL)
print('Total matches:', len(matches))
for match in matches[:5]:
    print('ID:', match[0])
    print('Expected:', match[2])
    print('Prompt first 100 chars:', repr(match[3][:100]))
    print('-'*20)
