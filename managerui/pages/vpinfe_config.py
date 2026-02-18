import os
from nicegui import ui
from common.iniconfig import IniConfig
from pathlib import Path
from platformdirs import user_config_dir
from frontend.qt_window_manager import trigger_app_restart

CONFIG_DIR = Path(user_config_dir("vpinfe", "vpinfe"))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
INI_PATH = CONFIG_DIR / 'vpinfe.ini'

_state = {
    'active_tab': None,
    'restart_pending': False 
}

IGNORED_SECTIONS = ['Generate']

# --- RESTORED DICTIONARY ---
SETTINGS_LABELS = {
    # [Settings]
    'vpxbinpath': 'VPX Executable Path',
    'vpximagepath': 'VPX Screenshots Dir',
    'vpxinipath' : 'VPX Ini Path',
    'tablerootdir': 'Tables Directory',
    'romrootdir': 'ROMs Directory',
    'pinmamepath': 'PinMAME Directory',
    'img_dir': 'Frontend Media Dir',
    'alt_exe': 'Alternate Launcher Exe',
    'vpx_args': 'VPX Launch Arguments',
    'startup_collection': 'Startup Collection',
    'theme': 'Active Theme',
    'loglevel': 'Log Verbosity',
    
    # [Displays]
    'tablescreenid': 'Playfield Monitor ID',
    'bgscreenid': 'Backglass Monitor ID',
    'dmdscreenid': 'DMD Monitor ID',
    'rotation': 'Playfield Rotation (0/90/270)',
    
    # [Network]
    'http_port': 'Web Server Port',
    'themeassetsport': 'Theme Server Port',
    'manageruiport': 'Manager UI Port',
}

def render_panel(tab=None):
    config = IniConfig(str(INI_PATH))
    sections = [s for s in config.config.sections() if s not in IGNORED_SECTIONS]
    
    if _state.get('active_tab') not in sections:
        _state['active_tab'] = sections[0]
    if 'restart_pending' not in _state:
        _state['restart_pending'] = False

    inputs = {}

    # --- ACTIONS ---
    def save_config():
        for section, keys in inputs.items():
            for key, inp in keys.items():
                val = inp.value
                save_val = "1" if isinstance(val, bool) and val else "0" if isinstance(val, bool) else str(val)
                config.config.set(section, key, save_val)
        
        with open(INI_PATH, 'w') as f:
            config.config.write(f)
        
        _state['restart_pending'] = True
        ui.notify('Changes Saved. (Restart required to apply)', type='info')

    def confirm_and_restart():
        restart_dialog.close()
        ui.notify('Restarting System...', type='positive')
        trigger_app_restart()

    def just_exit():
        restart_dialog.close()
        ui.run_javascript('window.close()')
        ui.notify('Manager Closed. You may close this tab.', type='warning')

    def attempt_exit():
        if _state.get('restart_pending', False):
            restart_dialog.open()
        else:
            just_exit()

    # --- UI LAYOUT ---
    with ui.column().classes('w-full'):
        
        # HEADER
        with ui.card().classes('w-full mb-6').style('background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%); border-radius: 12px;'):
            with ui.row().classes('w-full items-center p-4 gap-3'):
                ui.icon('tune', size='32px').classes('text-white')
                ui.label('VPinFE Configuration').classes('text-2xl font-bold text-white')
                ui.space()
                # ID is Critical for Context Menu Clicking
                ui.button(icon='close', on_click=attempt_exit).props('id=main-exit-btn flat round color=white size=lg')

        # DIALOG
        with ui.dialog() as restart_dialog, ui.card():
            ui.label('Settings have changed. Reload the cabinet?')
            with ui.row().classes('w-full justify-end'):
                ui.button('No', on_click=just_exit).props('flat color=grey')
                ui.button('Yes', on_click=confirm_and_restart).props('color=red')

        # TABS
        with ui.tabs().classes('w-full').props('inline-label dense').bind_value(_state, 'active_tab') as tabs:
            for section in sections:
                ui.tab(section, label=section)

        # PANELS
        with ui.tab_panels(tabs).classes('w-full').bind_value(_state, 'active_tab'):
            for section in sections:
                with ui.tab_panel(section):
                    inputs[section] = {}
                    with ui.card().classes('p-4 w-full'):
                        for key, value in config.config.items(section):
                            # --- USE DICTIONARY HERE ---
                            friendly_label = SETTINGS_LABELS.get(key, key)
                            
                            str_val = str(value).lower()
                            is_bool = str_val in ('true', 'yes', 'on', '1', 'false', 'no', 'off', '0')
                            bool_val = str_val in ('true', 'yes', 'on', '1')

                            with ui.row().classes('w-full items-center justify-between no-wrap'):
                                if is_bool:
                                    inputs[section][key] = ui.switch(text=friendly_label, value=bool_val)
                                else:
                                    is_path = any(x in key.lower() for x in ['path', 'dir', 'root', 'img_dir'])
                                    is_file_type = any(x in key.lower() for x in ['exe', 'bin', 'alt_exe', 'ini'])
                                    mode = 'file' if is_file_type else 'folder'

                                    with ui.row().classes('items-center gap-2 no-wrap'):
                                        inp = ui.input(label=friendly_label, value=value).style('width: 400px')
                                        inputs[section][key] = inp

                                        if is_path or is_file_type:
                                            async def open_picker(target=inp, m=mode):
                                                from frontend.qt_window_manager import pick_native_path
                                                new = await pick_native_path(m)
                                                if new: target.value = new
                                            ui.button(icon='folder_open', on_click=open_picker).props('flat dense round')
        
        # SAVE BUTTON
        with ui.row().classes('w-full justify-end mt-4'):
            ui.button('Save Changes', icon='save', on_click=save_config).props('color=primary rounded').classes('px-6')