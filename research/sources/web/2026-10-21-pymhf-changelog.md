<!--
  source: web
  url: https://monkeyman192.github.io/pyMHF/docs/change_log.html
  final_url: https://monkeyman192.github.io/pyMHF/docs/change_log.html
  retrieved: 2026-10-21
  http_status: 200
  content_type: text/html; charset=utf-8
  sha256: 57427fd3798c6df3c49a91cec3c53cf1c5f93338844be4d32a7ee61e481b7ff3
  why: pyMHF changelog (0.2.5 changes, attach mode)
-->

Skip to main content

 Ctrl+K

pyMHF documentation

 Usage guide

 API docs

 Search
 Ctrl+K

System Settings

Light

Dark

 GitHub

 Search
 Ctrl+K

 Usage guide

 API docs

System Settings

Light

Dark

 GitHub

 Collapse Sidebar
 Expand Sidebar

Section Navigation

Usage

Configuring pyMHF

Writing Mods

Creating hook definitions

Mod States

Inter-mod functionality

Partial Structs

Container Structs

Single-file mods

Extension types

Creating modding API’s with pyMHF

Writing Libraries

Custom Callbacks

GUI

Custom Widgets

Automatic-GUI

Hex View

HTTP API

Change Log

Usage guide

Change Log

Change Log#

0.2.5 (21/10/2026)#

Cleaned up the c_enum implementation to have a single base class to ensure consistency across inheriting types.

Changed the string representation of c_enum types (eg. c_enum8, etc.) so that the value is now the name of the associated enum value. The old form is now available via repr().

Added the disabled_mods setting which takes a list of mod names which will not be loaded. The files these mods are defined in aren’t imported at all, so no code in them is run. See here for more details. (c/o @Carbonster)

Mods decorated with @disable are now also detected before their file is imported, so their file isn’t imported at all (previously the file was imported and only the mod class itself was skipped). (c/o @Carbonster)

Added API for enabling and disabling mods via the mod_manager instance. Mods can also be enabled and disabled from the GUI. (#118)

Fixed an issue with GUI widget labels not being able to be reverted back to their original name after being modified.

Added the __main__.py file back so that pyMHF can be evoked by python -m pyMHF.

Fixed an issue with nested groups. (#123)

Dropped support for python 3.9. It has been EOL for quite some time so this is a long time coming really. from __future__ import annotations should no longer be required.

Added support for python 3.14 and above. This was achieved by updating pyrun-injected to 0.2.1 which fixes many of the injection issues we had before.

0.2.4 (16/08/2026)#

Fixed an issue where the _vector type incorrectly calculated the length of the vector.

Add a colour picker widget. This is implemented as the decorator COLOUR (or COLOR for the Americans).

Fixed an issue where quotation marks were added to STRING values in the UI.

Fixed an issue where, if an exception occurred during the calling of a one_shot detour, the detour wouldn’t be unregistered. (#109)

Added the ability to bind properties and methods to HTTP endpoints and generate OpenAPI docs based on this. See here for more details.

Moved the partial_struct decorator and Field dataclass to pymhf.core.structs.partial_struct.

Added ContainerStruct and Pattern to facilitate finding fields or globally defined objects at run-time. (#98 <https://github.com/monkeyman192/pyMHF/issues/98>_)

Fixed an issue where, if a new GUI property was added before any others and the mod was reloaded, an error would occur. (#111)

Fixed an issue where, if a GUI group was deleted, the bound functions under it weren’t unlinked from the GUI properly.

0.2.3 (08/04/2026)#

Changed the underlying type for the pymhf.extensions.ctypes.c_enumN types so that they subclass from unsigned integers instead of signed integers.

Added the c_enum8 type for creating enums whose value is serialized as an 8bit integer.

Added a toggle in the gui settings to enable reloading modules. When enabled, reloading a mod will reload all other python modules in the same directory. Anything within a .venv folder within the same directory will NOT be reloaded, neither will a file containing a mod (other than the original mod file being reloaded).

0.2.2 (11/02/2026)#

Deprecated the gui_combobox decorator. This is replaced by ENUM which is more native and flexible.

Added the is_slider argument to the INTEGER and FLOAT decorators to allow creating slider fields rather than numerical entry fields.

Added a custom widget class which allows mod authors to create completely unique GUI elements which can be bound to the state of the mod - CustomWidget. See here for the full usage guide.

Added the gui_group context manager to allow grouping widgets logically in the gui. (#93)

Added the c_char_p32 and c_char_p64 classes as wrappers for ctypes.c_uint32 and ctypes.c_uint64 types. This is to get around issues with using ctypes.c_char_p as a argument type to annotate char* types (the binary being hooked would often crash).

If the [pymhf].exe attribute is specified in the pymhf.toml as an absolute path, it will be used over the steam_gameid. This is required if one wants to use the [pymhf].start_paused attribute.

Fixed an issue with partial structs inheritence where, if a base class has a _total_size_ attribute, then the inheriting class would have the wrong offsets for fields.

Added the c_enum16 type for creating enums whose value is serialized as a 16bit integer.

Fixed an issue where the pattern cache wouldn’t be able to be created under certain circumstances when running a single-file mode (#94).

Added the ability to specify runtime callable functions in libraries via an entry-point so that certain functions in the library may be called before mod instantiation occurs. See here for more details.

Fixed an issue where single-file mods which imported a library didn’t load the specified internal mod directory.

0.2.1 (15/11/2025)#

Fixed an issue where ctypes.Union types weren’t accepted as a valid function argument type.

Added the ability to specify the type of a function argument using typing.Annotated to improve type hinting in libraries.

0.2.0 (02/10/2025)#

This release makes a milstone in stability and functionality for pyMHF.
The API for hooking functions should be considered “stable” from this point onwards and is unlikely to change significantly in the future (I hope!).
Next release set will focus on UI/UX as well as utilities, both in terms of the GUI and in the code.

Further improved partial structs to allow nesting references to themselves as a type (must be “indirect”, ie. the type of a pointer, or dynamic array for example).

Added a fallback method to calculate the binary hash in case opening the file fails. (c/o @sparrow)

Fixed some inssues around running python files directly with pymhf run

Added the option to pass command line arguments to the function when pymhf starts the process itself.

Added the config_overrides argument to load_mod_file to allow overriding the static config values.

Implemented the functionality so that if [pymhf].start_paused is True, the program will start automatically once injection is completed (no need for manual input any more).

0.1.16 (16/08/2025)#

Improved hooking performance by using the bulk enable mode in minhook. (#26)

Fixed an issue running mods where attach to already existing processes.

Fixed an issue with getting the caller offset address.

Added the ability to specify an already running processes’ PID to attach pyMHF. (#75)

Made run_module a public method as the recommended way to invoke pyMHF from code. (#76)

Added config options to not use the interactive python interpreter and not show the log window. (#76)

Added pyrun_injected as a dependency to allow injecting python versions greater than 3.11.

Improved custom callback functionality by allowing extra arguments to be passed to the called functions.

0.1.15 (16/07/2025)#

Fixed an issue where the this argument wouldn’t get correctly determined to be a pointer.

Added the configured mod directory to the system path to aide in inter-mod communication.

Improved support for mod folders which contained sub-folder for each mod. Now each folder is added to the system path if it contains any mods. (#71)

0.1.14 (09/07/2025)#

Added the ability for partial classes to subclass from another partial struct or ctypes.Structure.

Change mod folder loading so that it will load from sub-folders as well. (#64)

Implement a offset cache - This will reduce start up times after the initial load for any pattern which has already been found for the same binary. (#2)

Changed the @disable decorator so that it can be applied to mods as well as hooks.

Made some internal changes so that mods which define the same hook (whether by having the same pattern or a different one that resolves to the same offset) will not cause a clash. (#53)

Fixed an issue that meant that the numbers logged for loaded mods and hooks wasn’t correct.

0.1.13 (26/06/2025)#

Fixed an issue where function definitions defined with a pointer as their this argument weren’t able to be called correctly.

Fixed an issue where calling a library directly with pymhf run <library path> wouldn’t be able to import the library.

Improved front-facing type hinting.

0.1.12 (23/06/2025)#

Identified and fixed partially by config changes and partially by documentation issues with pyMHF being run with uv. Thanks to @Foundit3923 for helping to figure out the issues.

Improved inter-mod communication.

Added the ability to specify the total size of a partial struct using the _total_size_ attribute. This will be utilised more in some upcoming changes which should simplify initialization of structs from memory using hooked functions.

Added a new way to specify the data required for hooking and calling functions. See here for more details. This method will completely replace the old method of using the __pymhf_func_offsets__ etc. “magic” mod attributes.

Added a c_enum32 type which can be used to construct enums as fields.

0.1.11 (29/04/2025)#

Added the pymhf.gui.decorators.gui_combobox decorator (partial work on #15).

Added the ability for mods to access each others’ attributes and methods. (#5). See here for more details.

Fixed a few issues regarding running pyMHF. Thanks to @Foundit3923 for helping to figure out the issues.

Fixed an issue where hooks of imported functions which have _result_ as an argument work.

Added pymhf.core.hooking.NOOP decorator which indicates that the original game function shouldn’t be called. (#20)

Added a hex editor to the pyMHF gui. This is accessible from the “Hex Viewer” tab of the gui and allows real time viewing of data, following pointer values, and capturing memory snapshots. (#43).

Fixed an issue with loading hooks. Thanks to @cengelha for finding the bug.

Added “always on top” gui setting to the config. Thanks to @cengelha for adding it.

Fixed an issue with the debug mode toggle in the GUI. (#49).

0.1.10 (26/02/2025)#

Added pymhf.core.hooking.get_caller decorator for detours. When added, this will determine the location the function was called from. (#34). NOTE: This currently will only work properly for 64bit applications.

Added an pymhf.core.hooking.exported hook to allow hooking functions which are exported by the main exe.

Added the pymhf.core.calling.call_exported function which allows exported functions by the game to be called.

Added the ability to specify in the pymhf.core.hooking.imported decorator whether the detour time is "before" or "after".

Fixed an issue where hooks defined using the manual_hook decorator didn’t use the __pymhf_func_offsets__ etc. variables defined. (Thanks to @hashcatHitman for finding the bug.)

Made improvements to the shutting down of pyMHF so that when the process it is attached to exits, so does pyMHF.

Added a class decorator pymhf.utils.partial_struct.partial_struct which can be used to create ctypes.Structure types without needing to know the entire layout of the struct. See here for details.

0.1.9 (23/01/2025)#

Added cmd mode to the configuration to run commands in any registered libraries.

Added transparency slider and “always on top” options to the pymhf window.

Made a fix to manual hooks which were being declared with a pattern and name only.

0.1.8 (26/12/2024)#

Add ability for single-file mods to be run by pymhf. (#19)

Changed the config system to use toml files. (#27)

Added ability for pymhf to be attached to an already running process. (#28)

0.1.7 (10/10/2024)#

Implement ability to call overloaded functions which have patterns.

Improve safety of hooking functions and keyboard bindings as well as GUI reload fix.

Added functions to set the main window active (#6) - Contributed by @Foundit3923

0.1.6 (08/09/2024)#

Add ability for GUI widgets to reload when their associated mod gets reloaded (#4)

Add extra_args option to GUI field type decorators (eg, FLOAT) which are passed through to DearPyGui (#8)

Fix issues with hooking multiple functions which are overloads of the same base function.

Add the ability for patterns to be hooked up using the FUNC_PATTERNS data in implementing libraries (#14)

0.1.5 (26/08/2024)#

Allow overriding of function return values.

Fixed issue with after manual hooks with a _result_ argument.

Implement pattern scanning functionality (#1)

0.1.4 (14/08/2024)#

Overhauled config system to provide a more user-friendly experience.

Fixed a critical bug in hooking which meant that no result was returned.

Fixed an issue injecting variables into pymhf.

0.1.3 (31/07/2024)#

Implemented manual hooks. These are a decorator which have the can take an offset, name, and function definition, and allow for hooking a function without having to rely on the underlying library which utilises pymhf.

Made changes so that libraries can be installed as plugins to pymhf so that they can be run like pymhf <libname>

0.1.2 (15/07/2024)#

Made improvements to config reading

0.1.1 (05/07/2024)#

Fixed issues loading applications which aren’t loaded with steam.

Fixed logging number of mods loaded.

Implemented custom triggers. They can be implemented by libraries which use this framework to enable custom triggers which are specific to the game/application.

Fixed some issues with reloading of mods when there are multiple mods all contributing to compound hooks, including hooks with completely disabled detours.

Added @no_gui decorator which can be applied to a Mod class to indicate that it doesn’t need to be shown in the GUI.

0.1.0 (30/06/2024)#

Initial release. Much of the functionality has been copied over from NMS.py which was how this project started.

previous

HTTP API

next

API docs

 © Copyright 2025, monkeyman192.

 Created using Sphinx 9.1.1.

 Built with the PyData Sphinx Theme 0.23.0.
