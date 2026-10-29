"""Shared desktop action categories; no host-specific feature variants."""
CAMERA_ACTIONS = {'connect', 'usb_prepare', 'driver_uninstall',
                  'restore', 'restore_auto', 'restore_verify', 'look_prepare', 'look_install',
                  'look_verify', 'look_restore', 'vertical_enable', 'vertical_disable',
                  'vertical_status', 'vertical_remove', 'sound_on', 'sound_off',
                  'sound_audition', 'sound_install', 'sound_verify', 'sound_restore_sound'}

POWER_ACTIONS = {'restore', 'restore_auto', 'look_install', 'look_restore',
                 'vertical_enable', 'vertical_disable', 'vertical_remove',
                 'sound_on', 'sound_off', 'sound_audition', 'sound_install', 'sound_restore_sound'}
DIRECT_ACTIONS = {'direct_fl23_enable', 'direct_fl23_disable', 'direct_vertical_enable', 'direct_vertical_disable', 'direct_slot_default',
                  'direct_look_import', 'direct_looks_import', 'direct_resume_looks', 'direct_factory_reset', 'direct_resume_factory', 'direct_install_all'}
DIRECT_ACTIONS |= {'direct_sound_enable','direct_sound_disable','direct_sound_restore','direct_resume_settings'}
POWER_ACTIONS |= DIRECT_ACTIONS
CAMERA_ACTIONS |= DIRECT_ACTIONS | {'direct_verify'}
POWER_ACTIONS.add('setup_all')
CAMERA_ACTIONS.add('setup_all')
CAMERA_ACTIONS.add('review_failed_names')
CAMERA_ACTIONS.add('usb_stability')
# PC Remote recipe jobs: camera I/O through the user-space PTP interface, so no
# administrator worker and no power confirmation (settings only, no firmware).
RECIPE_ACTIONS = ('recipe_plan', 'recipe_apply')
REMOTE_ACTIONS = set(RECIPE_ACTIONS)
# The jobs whose macOS administrator worker runs with libusb's debug log on (LIBUSB_DEBUG=4, about
# 10 MB/min of root-owned log): every camera write, since a failed write is the case that needs a trace,
# and the USB stability check the user asks for by name. Read-only routine jobs (Detect, Test, Eject,
# the verifies) run without it. An explicit LIBUSB_DEBUG passes through for any job.
LIBUSB_TRACED_ACTIONS = frozenset(POWER_ACTIONS | {'usb_stability'})
