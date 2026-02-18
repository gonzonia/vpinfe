import os
from nicegui import ui
from common.iniconfig import IniConfig
from common.vpxcollections import VPXCollections
from pathlib import Path
from platformdirs import user_config_dir
from frontend.qt_window_manager import pick_native_path
import queue


CONFIG_DIR = Path(user_config_dir("vpinfe", "vpinfe"))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
INI_PATH = CONFIG_DIR / 'vpinfe.ini'
COLLECTIONS_PATH = CONFIG_DIR / 'collections.ini'
_state = {'active_tab': None}

# --- Friendly Name Mapping ---
SETTINGS_LABELS = {
    # [Settings] - Paths
    'vpxbinpath': 'VPX Executable Path',
    'vpximagepath': 'VPX Screenshots Dir',
    'vpxinipath' : 'VPX Ini Path',
    'tablerootdir': 'Tables Directory',
    'romrootdir': 'ROMs Directory',
    'pinmamepath': 'PinMAME Directory',
    'img_dir': 'Frontend Media Dir',
    'alt_exe': 'Alternate Launcher Exe',
    'vpx_args': 'VPX Launch Arguments',
    
    # [Settings] - Options
    'startup_collection': 'Startup Collection',
    'theme': 'Active Theme',
    'loglevel': 'Log Verbosity',
    
    # [Displays]
    'display': 'Playfield Monitor Index',
    'rotation': 'Playfield Rotation (0/90/270)',
    'backglass_display': 'Backglass Monitor Index',
    'dmd_display': 'DMD Monitor Index',
    'tableorientation': 'Table Orientation',
    
    # [Network]
    'port': 'Web Server Port',
    'manageruiport': 'Manager UI Port',
    'themeassetsport': 'Theme Assets Port',
}

def get_label(key: str) -> str:
    """Returns the friendly label if defined, otherwise formats the key."""
    if key in SETTINGS_LABELS:
        return SETTINGS_LABELS[key]
    # Fallback: "some_key_name" -> "Some Key Name"
    return key.replace('_', ' ').replace('-', ' ').title()

def _get_collection_names():
    """Get list of collection names for the dropdown."""
    try:
        collections = VPXCollections(str(COLLECTIONS_PATH))
        return [''] + collections.get_collections_name()  # Empty option + all collections
    except Exception:
        return ['']


def _get_installed_theme_names():
    """Get list of installed theme names."""
    themes = []
    themes_dir = CONFIG_DIR / 'themes'
    if themes_dir.is_dir():
        for entry in os.scandir(themes_dir):
            if entry.is_dir():
                themes.append(entry.name)
    return sorted(themes)

# Sections to ignore
IGNORED_SECTIONS = {'VPSdb'}

# Icons for each section (fallback to 'settings' if not defined)
SECTION_ICONS = {
    'Settings': 'folder_open',
    'Input': 'sports_esports',
    'Logger': 'terminal',
    'Media': 'perm_media',
    'Displays': 'monitor',
}

def render_panel(tab=None):
    config = IniConfig(str(INI_PATH))
    sections = [s for s in config.config.sections() if s not in IGNORED_SECTIONS]
    
    # Initialize active tab if first run
    if _state['active_tab'] not in sections:
        _state['active_tab'] = sections[0]

    ui.add_head_html('''
    <style>
        .config-card { background: linear-gradient(145deg, #1e293b 0%, #152238 100%) !important; border: 1px solid #334155 !important; border-radius: 12px !important; }
        .config-input .q-field__control { background: #1a2744 !important; border-radius: 8px !important; }
        .q-tab-panels, .q-tab-panel { background: #0d1a2d !important; }
    </style>
    ''')

    inputs = {}

    def save_config():
        for section, keys in inputs.items():
            for key, inp in keys.items():
                val = inp.value
                save_val = "1" if isinstance(val, bool) and val else "0" if isinstance(val, bool) else str(val)
                config.config.set(section, key, save_val)
        with open(INI_PATH, 'w') as f:
            config.config.write(f)
        ui.notify('Configuration Saved', type='positive')

    with ui.column().classes('w-full'):
        # Header Card
        with ui.card().classes('w-full mb-6').style('background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%); border-radius: 12px;'):
            with ui.row().classes('w-full items-center p-4 gap-3'):
                ui.icon('tune', size='32px').classes('text-white')
                ui.label('VPinFE Configuration').classes('text-2xl font-bold text-white')

        # Tabs with persistent binding
        with ui.tabs().classes('w-full').props('inline-label dense').bind_value(_state, 'active_tab') as tabs:
            for section in sections:
                ui.tab(section, label=section, icon=SECTION_ICONS.get(section, 'settings'))

        with ui.tab_panels(tabs).classes('w-full').bind_value(_state, 'active_tab'):
            for section in sections:
                with ui.tab_panel(section):
                    inputs[section] = {}
                    with ui.card().classes('config-card p-4 w-full'):
                        section_items = config.config.items(section)

                        with ui.column().classes('gap-3'):
                            for key, value in section_items:
                                friendly_label = get_label(key)
                                str_val = str(value).lower()
                                is_bool = str_val in ('true', 'yes', 'on', '1', 'false', 'no', 'off', '0')
                                bool_val = str_val in ('true', 'yes', 'on', '1')

                                with ui.row().classes('w-full items-center justify-between no-wrap'):
                                    if is_bool:
                                        inputs[section][key] = ui.switch(text=friendly_label, value=bool_val).classes('config-input')
                                    elif section == 'Settings' and key in ['startup_collection', 'theme']:
                                        opts = _get_collection_names() if key == 'startup_collection' else _get_installed_theme_names()
                                        inputs[section][key] = ui.select(label=friendly_label, options=opts, value=value).classes('config-input w-64')
                                    else:
                                        # Correctly handle File vs Folder
                                        is_path = any(x in key.lower() for x in ['path', 'dir', 'root', 'img_dir'])
                                        is_file_type = any(x in key.lower() for x in ['exe', 'bin', 'alt_exe', 'ini'])
                                        mode = 'file' if is_file_type else 'folder'

                                        with ui.row().classes('items-center gap-2 no-wrap'):
                                            inp = ui.input(label=friendly_label, value=value).classes('config-input').style('width: 400px')
                                            inputs[section][key] = inp

                                            if is_path or is_file_type:
                                                # MUST BE ASYNC to prevent Connection Lost
                                                async def open_picker(target=inp, m=mode):
                                                    new = await pick_native_path(m)
                                                    if new: target.value = new
                                                
                                                ui.button(icon='folder_open', on_click=open_picker).props('flat dense round color=grey')

        # Save Button
        with ui.row().classes('w-full justify-end mt-4'):
            ui.button('Save Changes', icon='save', on_click=save_config).props('color=primary rounded').classes('px-6')