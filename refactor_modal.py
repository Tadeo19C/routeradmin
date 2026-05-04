import sys

with open(r'd:\routerfleet\templates\router_manager\router_details.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Extract modal content
start_idx = -1
end_idx = -1
for i, line in enumerate(lines):
    if '<div class="p-3 bg-light text-right">' in line:
        start_idx = i
    if '</table>' in line and start_idx != -1:
        end_idx = i
        break

if start_idx != -1 and end_idx != -1:
    modal_content = lines[start_idx:end_idx + 2] # Include </table> and </div>
    
    # We want to insert the buttons 'Compare Selected Backups' and the table replacing the button container inside the card
    button_start_idx = -1
    button_end_idx = -1
    for i, line in enumerate(lines):
        if 'class="col-lg-12 text-center p-4"' in line and '<button' not in line:
            button_start_idx = i
            button_end_idx = i + 4
            break
            
    if button_start_idx != -1:
        # We need to drop the modal definition completely
        modal_start_idx = -1
        modal_end_idx = -1
        for i, line in enumerate(lines):
            if '<!-- Premium Backup Modal -->' in line:
                modal_start_idx = i
            if '{% block custom_page_scripts %}' in line:
                modal_end_idx = i - 2
                break
                
        # Now construct the final string doing replacements
        
        # New card body content
        new_card_content = []
        new_card_content.append('                                <div class="col-lg-12 pb-3">\n')
        # Include refresh button aligned right
        new_card_content.append('                                    <div class="p-3 text-right">\n')
        new_card_content.append('                                        <button type="button" class="btn btn-sm btn-outline-primary mr-2" onclick="location.reload()"><i class="fas fa-sync-alt"></i> Refresh Page</button>\n')
        new_card_content.append('                                        <button class="btn btn-info btn-sm" onclick="compareSelectedBackups()"><i class="fas fa-columns"></i> Compare Selected Backups</button>\n')
        new_card_content.append('                                    </div>\n')
        
        # Then the table directly (starts at the table responsive div)
        table_start = 0
        for i, line in enumerate(modal_content):
            if '<div class="table-responsive">' in line:
                table_start = i
                break
        
        new_card_content.extend(modal_content[table_start:])
        
        # Assemble
        part1 = lines[:button_start_idx]
        part2 = new_card_content
        part3 = lines[button_end_idx+1:modal_start_idx]
        part4 = lines[modal_end_idx:]
        
        with open(r'd:\routerfleet\templates\router_manager\router_details.html', 'w', encoding='utf-8') as fw:
            fw.writelines(part1 + part2 + part3 + part4)
            print('Successfully refactored DOM inline.')
else:
    print('Failed to find matching strings')
