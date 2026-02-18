import os
from nicegui import ui
from common.iniconfig import IniConfig
from common.vpxcollections import VPXCollections
from pathlib import Path
from platformdirs import user_config_dir

CONFIG_DIR = Path(user_config_dir("vpinfe", "vpinfe"))
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
INI_PATH = CONFIG_DIR / 'vpinfe.ini'
COLLECTIONS_PATH = CONFIG_DIR / 'collections.ini'

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
    # Re-read config from disk each time the page is opened
    config = IniConfig(str(INI_PATH))

    # Add custom styles for config page
    ui.add_head_html('''
    <style>
        .config-card {
            background: linear-gradient(145deg, #1e293b 0%, #152238 100%) !important;
            border: 1px solid #334155 !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2) !important;
            transition: all 0.2s ease !important;
        }
        .config-card:hover {
            border-color: #3b82f6 !important;
            box-shadow: 0 8px 12px -2px rgba(59, 130, 246, 0.15) !important;
        }
        .config-card-header {
            background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
            margin: -16px -16px 16px -16px;
            padding: 12px 16px;
            border-radius: 12px 12px 0 0;
        }
        .config-input .q-field__control {
            background: #1a2744 !important;
            border-radius: 8px !important;
        }
        .config-input .q-field__label {
            color: #94a3b8 !important;
        }
        .q-tab-panels {
            background: #0d1a2d !important;
        }
        .q-tab-panel {
            background: #0d1a2d !important;
        }
    </style>
    ''')

    # Dictionary to store all input references: {section: {key: input_element}}
    inputs = {}

    # Get all sections, filter out ignored ones
    sections = [s for s in config.config.sections() if s not in IGNORED_SECTIONS]

    def save_config():
        for section, keys in inputs.items():
            for key, inp in keys.items():
                config.config.set(section, key, inp.value)
        with open(INI_PATH, 'w') as f:
            config.config.write(f)
        ui.notify('Configuration Saved', type='positive')

    with ui.column().classes('w-full'):
        # Header card
        with ui.card().classes('w-full mb-6').style(
            'background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%); '
            'border-radius: 12px;'
        ):
            with ui.row().classes('w-full items-center p-4 gap-3'):
                ui.icon('tune', size='32px').classes('text-white')
                ui.label('VPinFE Configuration').classes('text-2xl font-bold text-white')

        # Tabs for each section - all on one row
        with ui.tabs().classes('w-full').props('inline-label dense') as tabs:
            for section in sections:
                icon = SECTION_ICONS.get(section, 'settings')
                ui.tab(section, label=section, icon=icon)

        # Tab panels with content
        with ui.tab_panels(tabs, value=sections[0] if sections else None).classes('w-full'):
            for section in sections:
                with ui.tab_panel(section):
                    inputs[section] = {}

                    with ui.card().classes('config-card p-4 w-full'):
                        # FIX: Use .items() to get (key, value) tuples directly.
                        # This avoids the "list indices must be integers" error.
                        section_items = config.config.items(section)

                        with ui.column().classes('gap-3'):
                            for key, value in section_items:
                                
                                friendly_label = get_label(key)  # Get our new friendly name

                                # Determine if it's a boolean (true/false)
                                bool_val = None
                                is_bool = False
                                str_val = str(value).lower() if value is not None else ""

                                if str_val in ('true', 'yes', 'on', '1'):
                                    bool_val = True
                                    is_bool = True
                                elif str_val in ('false', 'no', 'off', '0'):
                                    bool_val = False
                                    is_bool = True

                                with ui.row().classes('w-full items-center justify-between no-wrap'):
                                    
                                    # 1. SWITCH (Boolean)
                                    if is_bool:
                                        inputs[section][key] = ui.switch(text=friendly_label, value=bool_val).classes('config-input')
                                    
                                    # 2. DROPDOWN (Startup Collection)
                                    elif section == 'Settings' and key == 'startup_collection':
                                        collection_options = _get_collection_names()
                                        if value and value not in collection_options:
                                            collection_options.append(value)
                                        
                                        inputs[section][key] = ui.select(
                                            label=friendly_label, 
                                            options=collection_options, 
                                            value=value
                                        ).classes('config-input').style('min-width: 200px;')
                                    
                                    # 3. DROPDOWN (Theme)
                                    elif section == 'Settings' and key == 'theme':
                                        theme_options = _get_installed_theme_names()
                                        if value and value not in theme_options:
                                            theme_options.append(value)
                                        
                                        inputs[section][key] = ui.select(
                                            label=friendly_label,
                                            options=theme_options,
                                            value=value
                                        ).classes('config-input').style('min-width: 200px;')

                                    # 4. TEXT INPUT (Everything else)
                                    else:
                                        # Dynamic width calculation
                                        val_len = len(str(value)) if value else 0
                                        char_width = max(val_len, len(friendly_label), 5)
                                        width_px = int(char_width * 10 * 1.1)
                                        width_px = max(width_px, 100)
                                        
                                        inputs[section][key] = ui.input(
                                            label=friendly_label, 
                                            value=value
                                        ).classes('config-input').style(f'width: {width_px}px;')

        # Save button
        with ui.row().classes('w-full justify-end mt-4'):
            ui.button('Save Changes', icon='save', on_click=save_config).props('color=primary rounded').classes('px-6')
