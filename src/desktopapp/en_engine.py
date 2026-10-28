"""English for what the worker and the engine print and raise, keyed by the Chinese source.

The engine keeps its own words on disk: worker.log, process.log and the status files stay verbatim.
The window shows these lines in English through engine_text.display(). A key keeps the code's own
%-specifiers, and %s where the code joins in a value (a + b, an f-string); its English keeps the same
specifiers in the same order and the same number of lines. Interface text for tr() stays in en.py;
dev/desktop/test_engine_text_coverage.py checks that every message in the source has an entry.
"""

ENGINE = {
    # desktopapp.platforms.macos_authorization: the Terminal password step.
    '请在打开的「终端」窗口中输入 Mac 登录密码（输入时不显示）。':
        'Enter your Mac login password in the Terminal window that opened. It stays hidden as you type.',
    '等待在「终端」窗口输入 Mac 登录密码；尚未接管 USB 或开始相机操作。输入密码前关闭终端窗口不会刷写相机。\n':
        'Waiting for your Mac login password in Terminal. USB is not taken over and no camera operation has started; closing Terminal before you enter the password writes nothing.\n',
    '管理员进程意外结束，相机操作结果未知。请导出诊断包，不要重复刚才的操作。':
        "Don't repeat the task. The administrator process ended unexpectedly, so the camera result is unknown. Export diagnostics.",
    '终端授权未完成（窗口已关闭或密码不正确）；本次相机操作尚未开始，可重新点击原按钮。':
        "Terminal authorization didn't finish (window closed or wrong password). The camera task hasn't started; click the same button to try again.",
    '终端授权未完成，相机操作未报告开始。请保留日志；系统详情：%s':
        'Terminal authorization did not finish, and the camera operation never reported a start. Keep the log. System details: %s',
    '相机授权 worker 必须由终端 sudo 启动。': 'The camera authorization worker must be started by sudo in Terminal.',
    '相机任务已结束，但文件所有权交还失败；请保留此日志。\n%s':
        'The camera job finished, but returning file ownership to your account failed. Keep this log.\n%s',

    # desktopapp.worker
    '读取相机程序文件以识别固件版本（只读）。': 'Reading the camera program files to identify the firmware build (read-only).',
    '准备本次线框测试的 USB 驱动与服务连接。': 'Preparing the USB driver and service connection for this frame test.',
    '先完成一次本页操作，再核对重新加载状态。': "Run this page's action once first, then verify the reload.",
    '所选目录没有旧备份恢复记录，本次没有连接相机。用内置原厂基准或固件文件恢复后，请点“重启后核对并完成恢复”。':
        'The chosen folder has no backup-restore record, so the camera was not connected. After a restore from the built-in factory data or a firmware file, click "Verify and finish".',
    '恢复尚未结束，请先点击“恢复／继续恢复”': 'The restore is not finished. Click "Restore…" first',
    '所选恢复记录不可用（保留原样）；按当前连接的相机重新生成内建原厂恢复计划。':
        "The chosen restore record can't be used (it stays as is). Planning the built-in factory restore from the connected camera.",
    '上次恢复写入已结束；先核对，不重复写入。': 'The last restore finished writing. Verifying first; nothing is written again.',
    '保留旧恢复记录，从当前相机重新生成内建原厂恢复计划；不重放旧任务。':
        'Keeping the old restore record and planning the built-in factory restore from the current camera. The old job is not replayed.',
    '当前连接的是另一台机身；该机身的旧记录保留不动。按当前相机重新生成恢复计划。':
        "A different camera is connected. The other camera's record stays as is; planning the restore for this one.",
    '相机内容已与上次恢复结果不同（%s），通常是之后又安装或修改过功能。旧记录保留；按当前相机字节重新生成原厂恢复计划。':
        "The camera no longer matches the last restore (%s), usually because features were installed or changed since. The old record stays; planning the factory restore from the camera's current bytes.",

    '上次恢复记录的固件版本是 %s，而相机现在是 %s。旧记录保留；按相机当前的固件版本和字节重新生成原厂恢复计划。':
        "The last restore recorded firmware build %s, but the camera is now %s. Its record stays; planning the factory restore for the camera's current build and bytes.",

    # desktopapp.allinone: one-click install.
    '本次一键安装已结束，没有重复写入。': 'This one-click install already finished. Nothing was written again.',
    '重新读取当前竖屏与线框状态，续接本次安装；相同内容不重复写入。':
        'Rereading the vertical display and frame state to continue this install. Content already in place is not written again.',
    '所选安装已完成；请在机身检查预览、名称、拍摄和回放。':
        'The selected install is complete. Check live view, names, shooting and playback on the camera.',
    '竖屏已保存开启，并已核对重开后的实际运行状态。': 'Vertical display is saved on, and was checked running after the restart.',
    '旧安装的竖屏仅在本次开机开启；可用新版竖屏页保存开启。':
        'This older install turned on vertical display until the camera powers off. Use the Vertical display page to keep it on.',
    '一键安装：%s': 'One-click install: %s',
    '执行：%s': 'Running: %s',
    '相机安装与重启核对已通过；只继续电脑端插件步骤。':
        'The camera install and its restart check passed. Continuing with the plugin step on the computer only.',
    '上次程序与名称已完整读回；核对当前内容后只继续设置，不重装驱动、不重复刷写程序。':
        'Programs and names from last time read back in full. After checking the camera, only the settings continue: no driver reinstall, no program rewrite.',
    '名称已经写好；核对／准备资源重新加载，不重写名称，不重装驱动。':
        'Names are already written. Checking and preparing the resource reload; names and drivers stay as they are.',
    '上次停在连接准备；本次只测试连接，不重复更换驱动。':
        'Last time stopped while preparing the connection. Testing the connection only; drivers stay as they are.',
    '继续已保存的安装计划；先核对新开机，不重新刷写。':
        'Continuing the saved install plan. Checking the fresh start first; nothing is rewritten.',
    '所有读写已结束。\n%s': 'All reads and writes are finished.\n%s',
    '本次程序／外观写入和完整读回已结束。\n%s': 'Programs and looks are written and read back in full.\n%s',
    '竖屏线框步骤没有返回已写入／已符合目标状态，请保留日志':
        "The vertical display frame step didn't report written or already in place. Keep the log",
    '竖屏持久化加载尚未确认，不以会话临时开启代替完成。请保留日志。':
        "The saved vertical display setting isn't confirmed loaded, and a temporary switch-on doesn't count. Keep the log.",
    '上次安装在写入前停止；保留失败记录，使用新版代码重新生成方案，不重装驱动。':
        'The last install stopped before writing. Keeping its record and planning again with this version; drivers stay as they are.',
    '上次在名称提交前空间不足；先核对现有字节并清理该次已完成的临时报告。':
        "Last time the camera ran out of space before the names were committed. Checking the current bytes and clearing that run's finished temporary reports first.",
    '；原始阶段：%s；原始错误：%s': '; original stage: %s; original error: %s',
    '缺少原始错误，请导出包含子事务的新诊断包': 'original error missing; export new diagnostics, which include the sub-transactions',
    '上次安装结果需要核对，不会重复刷写。保留本目录并查看完整错误：%s%s':
        "The last install's result needs checking, so nothing is rewritten. Keep this folder and read the full error: %s%s",

    # Lines the worker builds from several messages, each catalogued whole (engine_text never pieces a
    # line together). The one-click summary appends the vertical display outcome:
    '所选安装已完成；请在机身检查预览、名称、拍摄和回放。竖屏已保存开启，并已核对重开后的实际运行状态。':
        'The selected install is complete. Check live view, names, shooting and playback on the camera. Vertical display is saved on, and was checked running after the restart.',
    '所选安装已完成；请在机身检查预览、名称、拍摄和回放。旧安装的竖屏仅在本次开机开启；可用新版竖屏页保存开启。':
        'The selected install is complete. Check live view, names, shooting and playback on the camera. This older install turned on vertical display until the camera powers off. Use the Vertical display page to keep it on.',
    # the review error joins the folder and the child job's stage and error:
    '上次安装结果需要核对，不会重复刷写。保留本目录并查看完整错误：%s；原始阶段：%s；原始错误：%s':
        "The last install's result needs checking, so nothing is rewritten. Keep this folder and read the full error: %s; original stage: %s; original error: %s",
    '上次安装结果需要核对，不会重复刷写。保留本目录并查看完整错误：%s；原始阶段：未知；原始错误：%s':
        "The last install's result needs checking, so nothing is rewritten. Keep this folder and read the full error: %s; original stage: unknown; original error: %s",
    # and the restart steps it prints (reloadguide.text(setup=True), plain and resource_reload) join
    # interface texts into these lines; the English matches the guide the window shows.
    '下一步：接回 USB，选择海量存储，再点首页“继续安装”。工具先核对加载，不重复刷写。':
        'Next: Reconnect USB in Mass Storage mode and click "Continue installation". The tool verifies the load first; it doesn’t write again.',
    '加载核对只读取状态，不会再刷一次。点“确定”只关闭说明，不会自动断电或代替你确认测试。':
        'Verifying only reads; it never writes again. "OK" only closes these steps. It doesn’t power anything off or confirm the test for you.',
    '开机后先不用拍照。接回 USB 海量存储，再点首页“继续安装”。工具会核对新的冷启动和只读挂载，然后继续剩余程序，不重复写名称、不重装驱动。':
        'No need to take a photo yet. Reconnect USB in Mass Storage mode, then click "Continue installation" on the One-click install page. The tool checks for a fresh cold start and the read-only mount, then writes the remaining programs. Names aren’t rewritten and drivers aren’t reinstalled.',

    # desktopapp.exiftool, official, presets, lookbatch, reviewnames
    '正在准备 Lightroom 的 ExifTool 辅助程序（仅电脑端，不连接相机）。':
        'Preparing ExifTool for Lightroom (on this computer only; the camera is not connected).',
    'ExifTool 自动下载失败，本次未开始相机操作。请检查网络后再点同一按钮；完整错误：\n%s':
        'ExifTool failed to download, so no camera operation started. Check the network and click the same button again. Full error:\n%s',
    'ExifTool 已就绪：%s': 'ExifTool ready: %s',
    '下载官方 ExifTool：%s': 'Downloading the official ExifTool: %s',
    'ExifTool 启动失败：%s\n%s': 'ExifTool failed to start: %s\n%s',
    '正在解码原厂文件，仅操作电脑文件…': 'Decoding the factory file on this computer…',
    '原厂文件已解码 %.0f MiB': 'Factory file decoded: %.0f MiB',
    '内置六款外观文件缺失，请使用完整工具包；尚未连接相机：%s':
        'Built-in look files are missing; use the complete app package. The camera was not connected: %s',
    '内置外观名称／照片阶段不符：%s': "A built-in look's name or photo stage doesn't match: %s",
    '请至少添加一个操作项；未添加的槽位保持原样。': "Add at least one change. Slots you don't add stay as they are.",
    '每个目标槽位只能有一个操作，范围为 1–6。': 'Each slot, 1 to 6, takes one change only.',
    '外观名称必须是文字。': 'The look name must be text.',
    '请为自订 %s 选择 A7Look 文件。': 'Choose an A7Look file for Custom %s.',
    '已确认此前没有提交名称或程序；只清理了对应临时报告／worker。原失败记录保留，下一次使用新的事务。':
        'Confirmed that no names or programs were committed. Cleared only the matching temporary reports and worker. The failed record stays; the next run starts a new transaction.',
    '核对已完成的名称失败报告、原程序窗口与名称绑定；不写固件或设置。':
        'Checking the finished name-failure report, the original program windows and name bindings. No firmware or settings are written.',

    # desktopapp.platforms.usb_drivers (Windows)
    '等待 Windows 管理员确认…': 'Waiting for Windows administrator approval…',
    '管理员进程已启动；正在实时读取进度。': 'The administrator process started. Reading its progress live.',
    '正在读取 Windows 驱动绑定…': 'Reading Windows driver bindings…',
    '正在检测 Sony 054C:%s 的现有驱动…': 'Checking the current driver for Sony 054C:%s…',
    '未发现 Sony USB 设备': 'no Sony USB device found',
    '无可读设备': 'no readable device',
    '已安装可用驱动，本次沿用，未重复安装': 'A working driver is already installed and was kept.',
    '正在建立相机服务连接（此步骤不写固件）；两种 USB 身份分别检查。':
        'Opening the camera service connection (this step writes no firmware). Checking both USB identities.',
    '正在让 Windows 重新识别设备…': 'Asking Windows to detect the device again…',
    '已列出所有 Sony USB 身份；未知 PID 不等于已确认的 A7C II。请核对设备名称、接口类型及海量存储模式，不会给未知设备自动换驱动。':
        'Listed every Sony USB identity. An unknown PID is not a confirmed A7C II: check the device name, interface type and Mass Storage mode. Unknown devices never get a driver change.',
    '未找到服务身份 054C:0336，请先使用“两阶段驱动与连接”入口。当前检测：%s。完整设备／接口信息已保存，不会为未知 PID 自动更换驱动。':
        'Service identity 054C:0336 not found. Use "Prepare drivers and test the connection" first. Found: %s. Full device and interface details are saved; unknown PIDs never get a driver change.',
    '未找到相机的海量存储身份 054C:0E8A，请在相机选择“海量存储”后重新连接。当前检测：%s。完整设备／接口信息已保存，不会为未知 PID 自动更换驱动。':
        "Choose Mass Storage on the camera, then reconnect. The camera's Mass Storage identity 054C:0E8A was not found. Found: %s. Full device and interface details are saved; unknown PIDs never get a driver change.",
    '054C:%s 已安装 %s，直接沿用，跳过驱动安装与管理员申请。':
        '054C:%s already has %s. Keeping it; no driver install or administrator prompt needed.',
    '驱动安装超过 180 秒，已停止等待；请保留日志核对当前绑定，不自动重复安装。':
        "The driver install ran over 180 seconds, so the wait stopped. Keep the log and check the current binding; the install won't repeat by itself.",
    '正在等待服务身份 054C:0336；出现后先检测驱动，已有可用绑定则跳过安装。':
        'Waiting for service identity 054C:0336. Its driver is checked when it appears; a working binding skips the install.',
    '服务身份已出现，检测现有驱动。': 'Service identity appeared. Checking its driver.',
    '服务连接成功，驱动准备结束。': 'Service connection works. Drivers are ready.',
    '正在备份驱动包：%s': 'Backing up driver package: %s',
    '正在卸载相机驱动包：%s': 'Removing camera driver package: %s',
    'Windows 驱动查询失败，不能据此判断相机未连接。libusb 当前检测：%s。本次未安装驱动或写入相机。原始查询错误：%s':
        "Windows couldn't list its drivers, so this doesn't show the camera is disconnected. libusb found: %s. No driver was installed and nothing was written to the camera. Original query error: %s",

    # desktopapp.usbcheck: the read-only connection stability check.
    '通过只说明这段时间内连续只读传输稳定；不保证刷写期间一定不掉线，也不代表线材认证。':
        'A pass means read-only transfers stayed stable for this period. It does not promise the link holds during a write, and it does not certify the cable.',
    '%d 轮只读传输均完成，共 %.1f MB，连续读取 %.0f 秒，逐轮字节一致。%s':
        '%d read-only rounds finished: %.1f MB over %.0f seconds, the same bytes every round. %s',
    'USB 稳定性检测未通过（%s）：%s。请换线或直连电脑 USB 接口后重测；本次没有固件或设置写入。':
        'USB stability check failed (%s): %s. Try another cable or a USB port on the computer itself, then test again. No firmware or settings were written.',
    'USB 稳定性检测：第 %d 轮只读读取程序文件（至少 %d 轮、连续 %d 秒），不写固件或设置。':
        'USB stability check: read-only round %d of the program files (at least %d rounds over %d seconds). No firmware or settings are written.',
    'USB 稳定性检测未完成：%s。本次没有固件或设置写入。': 'USB stability check incomplete: %s. No firmware or settings were written.',
    '已读 %d 轮，达到轮数上限，但连续读取只持续 %.0f 秒，未满 %d 秒；本次不算通过':
        'read %d rounds, the most allowed, but reading lasted only %.0f of the %d seconds needed, so this run does not pass',
    '第 %d 轮': 'round %d',
    '连接阶段': 'while connecting',
    '程序文件未完整读回：%s': 'a program file did not read back in full: %s',
    '重复读回的字节不一致：%s': 'repeated reads returned different bytes: %s',
    '读取 %s 只有 %.2f MB/s，低于 %.1f MB/s；连接可能经过 USB 1.1、扩展坞或线材质量较差':
        'reading %s ran at %.2f MB/s, under %.1f MB/s; the link may go through USB 1.1, a hub or a poor cable',

    # desktopapp.actions.sound_state
    '当前自定义声音配置不存在，请重新保存或恢复原厂音效。':
        "The camera's custom sound settings are missing. Save the sound again, or restore the factory sound.",
    '当前声音文件长度与配置不同。': 'The sound file on the camera is not the length its settings expect.',
    '当前声音尚未按磁盘配置加载，请按写入后的提示断电重开。':
        "The camera hasn't loaded the saved sound yet. Do the cold restart the dialog showed after the write.",

    # looktool.buildprofile and devicesession: the firmware identity gate and other-build refusals.
    '此相机的固件版本不受支持，未写入任何内容。（appFw.so %s…，cpapp-b.bin %s…）':
        "This camera's firmware build isn't supported. Nothing was written. (appFw.so %s…, cpapp-b.bin %s…)",
    '尚未识别此相机的固件版本，未写入任何内容。': "This camera's firmware build hasn't been identified, so nothing was written.",
    '所保存的内容来自固件版本 %s，而相机是 %s，未写入任何内容。':
        'The saved bytes come from firmware build %s, but the camera is %s. Nothing was written.',
    '无法确定所保存的内容来自哪个固件版本，未写入任何内容。':
        "The firmware build of the saved bytes can't be identified, so nothing was written.",
    '所选原厂文件是固件版本 %s，而相机是 %s，未写入任何内容。':
        'The chosen Sony firmware file is build %s, but the camera is %s. Nothing was written.',
    '所选原厂文件不是受支持的固件版本，未写入任何内容。':
        "The chosen Sony firmware file isn't a supported build, so nothing was written.",
    '此任务记录的固件版本是 %s，而相机现在是 %s，没有核对或写入任何内容。':
        'This job recorded firmware build %s, but the camera is now %s. Nothing was verified or written.',

    # looktool.devicesession
    '等待相机普通 USB 连接（最多 %d 秒）。%s': "Waiting up to %d seconds for the camera's normal USB connection. %s",
    '普通 USB 身份未出现；只读取已有服务会话的机身序列，核对后续接，不重复认证。':
        "The normal USB identity didn't appear. Reading only the camera serial from the open service session, then continuing; no new authentication.",
    '相机没有以普通“海量存储”身份连接（可能仍停在上次的服务模式 054C:0336）。请拔掉 USB、关机并取出电池约 1 分钟，再开机选择海量存储、接回 USB 后重试；本次没有写入相机。（Normal Mass Storage USB serial is required for body binding）':
        'Unplug USB, turn the camera off and take the battery out for about 1 minute. Then turn it on, choose Mass Storage, reconnect USB and try again. The camera did not connect as Mass Storage (it may still be in service mode, 054C:0336). Nothing was written. (Normal Mass Storage USB serial is required for body binding)',
    '读取相机文件时 USB 通信出错：%s': 'USB error while reading camera file: %s',
    '已清理上次只读检测留下的报告（不影响相机内容），继续本次操作。':
        'Cleared the report the last read-only check left (camera content unaffected). Continuing.',

    # looktool.checkpointworker: name files, backups and their cleanup.
    '请完整断电重开（拔 USB、关机、取下电池至少 1 分钟后装回开机），再接回 USB 点同一个恢复按钮。':
        'Do a cold restart (unplug USB, turn the camera off, take the battery out for at least 1 minute, put it back and turn on), then reconnect USB and click the same restore button.',
    '相机 /usr 分区的临时空间用完了：已恢复 %d/%d 个名称文件，程序和已恢复的部分保持不变，相机可以正常开机使用。旧文件占用的空间要断电后才释放。%s只会处理剩下的部分。':
        "The camera's /usr partition ran out of temporary space: %d/%d name files restored. Programs and the restored files are unchanged, and the camera starts and works normally. Old files free their space only after a power-off. %s Only the remaining files are processed.",
    '写入前检查发现相机 /usr 分区临时空间不足，本次没有写入。%s':
        "The pre-write check found too little temporary space on the camera's /usr partition. Nothing was written. %s",
    '相机 /usr 分区仍处于可写挂载，通常是上一次操作后还没有完整断电重开；本次没有写入。%s':
        "The camera's /usr partition is still mounted writable, usually because the camera has not had a cold restart since the last operation. Nothing was written. %s",
    '名称内容已完成，但只读挂载忙碌；需要完成设置与重新加载准备后再重开核对。':
        'Names are done, but the read-only mount is busy. Finish the settings and reload preparation, then restart and verify.',
    '旧任务名称备份清理未完成，相机名称文件没有改动；请完整断电重开后再点恢复。Backup cleanup incomplete: %s':
        "The old job's name backup cleanup didn't finish; the camera's name files are unchanged. Do a cold restart, then click restore again. Backup cleanup incomplete: %s",

    # A failed name operation raises its guidance followed by the native report (checkpointworker.py:155).
    '相机 /usr 分区的临时空间用完了：已恢复 %d/%d 个名称文件，程序和已恢复的部分保持不变，相机可以正常开机使用。旧文件占用的空间要断电后才释放。%s只会处理剩下的部分。Checkpoint name operation incomplete: %s':
        "The camera's /usr partition ran out of temporary space: %d/%d name files restored. Programs and the restored files are unchanged, and the camera starts and works normally. Old files free their space only after a power-off. %s Only the remaining files are processed. Checkpoint name operation incomplete: %s",
    '写入前检查发现相机 /usr 分区临时空间不足，本次没有写入。%sCheckpoint name operation incomplete: %s':
        "The pre-write check found too little temporary space on the camera's /usr partition. Nothing was written. %s Checkpoint name operation incomplete: %s",
    '相机 /usr 分区仍处于可写挂载，通常是上一次操作后还没有完整断电重开；本次没有写入。%sCheckpoint name operation incomplete: %s':
        "The camera's /usr partition is still mounted writable, usually because the camera has not had a cold restart since the last operation. Nothing was written. %s Checkpoint name operation incomplete: %s",
    '名称内容已完成，但只读挂载忙碌；需要完成设置与重新加载准备后再重开核对。Checkpoint name operation incomplete: %s':
        'Names are done, but the read-only mount is busy. Finish the settings and reload preparation, then restart and verify. Checkpoint name operation incomplete: %s',

    # looktool.compilelook, coupledfit: making an A7Look on the computer.
    '已生成近似结果；最终优化未完全收敛。验证色样平均预测误差 %.2f / 255，不能代表实机色彩准确度。':
        "Made an approximate result; the final optimisation didn't fully converge. Mean prediction error on the check patches is %.2f / 255, which doesn't measure colour accuracy on the camera.",
    '初始拟合达到迭代预算，保留当前近似值继续优化；不会中断转换。':
        'The first fit used its iteration budget. Keeping the current approximation and optimising on; the conversion continues.',

    # looktool.direct: the write, read-back and reload steps.
    '读取当前状态': 'Reading the current state',
    '恢复计划已生成': 'Restore plan ready',
    '所选操作的写入计划已生成': 'Write plan ready',
    '恢复并核对名称资源': 'Restoring and checking names',
    '核对名称资源': 'Checking names',
    '恢复原厂外观设置': 'Restoring the factory look settings',
    '应用并核对所选设置': 'Applying and checking the selected settings',
    '准备重新加载': 'Preparing the reload',
    '写入前检查通过，接下来应用更改': 'Pre-write check passed; applying the changes next',
    '正在应用所选操作': 'Applying the selected changes',
    '读回完成，等待断电重开': 'Read-back done; waiting for a cold restart',
    '加载状态符合目标': 'The camera loaded what was written',
    '完成': 'Done',
    '已停止，请保留日志核对结果': 'Stopped. Keep the log to check the result',
    '名称已写好；请按提示断电重开，再继续程序安装': 'Names written. Do the cold restart as prompted, then continue the program install',
    '名称及只读挂载已确认，可以继续程序安装': 'Names and read-only mount confirmed; the program install can continue',
    'FL23 操作完成：已写入并完整读回；重开后生效，无需再点核对。':
        'FL2/FL3 done: written and read back in full. They work after a restart; no need to verify.',
    '恢复尚未完成：写入与读回已结束，等待重启后核对': 'Restore not finished: writing and read-back are done. Waiting for the check after a restart',
    '已清理旧任务遗留的名称备份 %d 个，释放相机 /usr 空间。':
        "Cleared %d name backups left by old jobs to free space on the camera's /usr partition.",
    '已核对程序和名称均符合原安装计划，只续做设置与重新加载准备；没有重复刷写程序。':
        'Programs and names match the install plan. Continuing with settings and reload preparation only; programs are not rewritten.',
    '所选槽位已保存为 ST。': 'The selected slot is saved as ST.',
    '只继续名称、设置与重新加载准备，不重复写入程序。':
        'Continuing names, settings and reload preparation only; programs are not rewritten.',
    '续接写入和读回已结束，恢复尚未完成：请拔 USB 和其他外部供电，等存取灯停止闪烁，再正常关机并等屏幕和灯完全熄灭；取下电池至少一分钟，再装回开机、接回 USB，点击“重启后核对并完成恢复”。':
        'Unplug USB and any other power, wait for the access lamp to stop blinking, then turn the camera off and wait until the screen and lamp are dark. Take the battery out for at least one minute, put it back, turn on, reconnect USB and click "Verify and finish". The continued write and read-back are done, but the restore is not finished.',
    '相机仍在运行上次写入前加载的程序，本次没有写入。请先拔 USB、关机，取下电池至少一分钟，再开机接回 USB，点击“重启后核对并完成恢复”或再次点击恢复。':
        'Unplug USB, turn the camera off and take the battery out for at least one minute. Then turn it on, reconnect USB, and click "Verify and finish" or restore again. The camera is still running the programs it loaded before the last write; nothing was written.',
    '先写入名称资源，成功后才写入程序。': 'Writing names first; programs follow only after they succeed.',
    '正在逐文件更新名称（共 %d 项）；名称完成后才写入程序。':
        'Updating names file by file (%d in all); programs follow once names are done.',
    '正在写入程序窗口批次 %d/%d': 'Writing program window batch %d/%d',
    '名称内容已完成；只读挂载忙碌。完成设置与重新加载准备后，需要断电重开核对挂载状态。':
        'Names are done; the read-only mount is busy. After the settings and reload preparation, do a cold restart so the mount can be verified.',
    '所有读写已结束。68 个名称已完整核对，程序和配方尚未写入。旧资源仍被占用，需要断电重开释放后，再点同一按钮继续；不重复写名称。':
        'All reads and writes are finished. All 68 names are verified; programs and recipes are not written yet. Do a cold restart to release the old resources, then click the same button to continue. Names are not written again.',
    '安装／关闭任务已结束，没有后续待写入步骤。以下断电仅用于让相机加载已写入的程序，电脑端核对可选。':
        'The install or removal job is finished; nothing is left to write. The cold restart below only makes the camera load the written programs. Verifying from the computer is optional.',
    '所有读写已结束。拔 USB 和其他外部供电，等存取灯停止闪烁，再正常关机并等屏幕和灯完全熄灭；取下电池至少一分钟，再装回开机、检查功能并核对。':
        'All reads and writes are finished. Unplug USB and any other power, wait for the access lamp to stop blinking, then turn the camera off and wait until the screen and lamp are dark. Take the battery out for at least one minute, put it back, turn on, check the features and verify.',
    '磁盘与设置已符合目标，本次没有重复写入；实际预览、照片和声音仍需在机身检查。':
        'The camera already matches the target, so nothing was written again. Check live view, photos and sound on the camera.',
    '所有读写已结束。名称已核对，程序未写入。只读挂载已恢复，无需额外重开。':
        'All reads and writes are finished. Names verified; programs not written. The read-only mount is back, so no extra restart is needed.',
    '所有读写已结束。名称已核对，程序未写入。请按弹窗断电重开后接回，继续剩余程序安装。':
        'All reads and writes are finished. Names verified; programs not written. Do the cold restart in the dialog, reconnect, and continue the program install.',
    '尚未确认新的冷启动与只读挂载；没有重复写入。请按弹窗完成断电重开、接回。':
        'Do the cold restart in the dialog and reconnect. No fresh cold start or read-only mount is confirmed yet; nothing was written again.',
    '尚未确认新的冷启动。完成断电重开后再核对，不要重复写入。':
        "No fresh cold start confirmed yet. Do the cold restart, then verify again; don't repeat the write.",
    '恢复写入已结束，请核对重新加载状态，不重复写入': 'Restore writing finished. Verify the reload; nothing is written again',
    '已完整读回确认程序与名称均符合原厂目标；只继续设置和重新加载准备，只读挂载将在新开机后核对。':
        'Programs and names read back and match the factory target. Continuing with settings and reload preparation only; the read-only mount is checked after the next start.',
    '无法确认当前加载状态；尚未开始续接写入': "Can't confirm what the camera loaded; the continued write hasn't started",
    '运行中程序与已记录的原状态／目标不符；保留日志，不自动重试':
        'The running programs match neither the recorded original nor the target. Keep the log; there is no automatic retry',
    '续接计划：剩余程序批次 %d，剩余名称文件 %d；已符合目标的内容不重复写入。':
        'Continuation plan: %d program batches and %d name files left. Content already in place is not written again.',
    '名称内容已完成；只读挂载忙碌，待完成设置后断电重开核对。':
        'Names are done; the read-only mount is busy. After the settings, do a cold restart and verify.',
    '恢复完成，所有读写已结束。拔 USB 和其他外部供电，等存取灯停止闪烁，再正常关机并等屏幕和灯完全熄灭；取下电池至少一分钟，再装回开机、检查并核对。':
        'Restore written; all reads and writes are finished. Unplug USB and any other power, wait for the access lamp to stop blinking, then turn the camera off and wait until the screen and lamp are dark. Take the battery out for at least one minute, put it back, turn on, check the camera and verify.',
    '原厂恢复后的 /usr 只读挂载尚未确认；不标记恢复完成，请保留日志':
        "The read-only /usr mount after the factory restore isn't confirmed, so the restore is not marked complete. Keep the log",
    '名称写入已完成，但尚未确认新开机后的只读挂载；不清理旧资源':
        "Names are written, but the read-only mount after the next start isn't confirmed. Old resources stay",

    # looktool.factoryrecover: resuming an interrupted factory restore.
    '相机执行插件仍存在，不能在执行期间覆盖；本次尚未恢复写入，请结束连接后完整断电再重试':
        "The camera's run plugin is still present and can't be overwritten while it runs. The restore hasn't written anything; disconnect, do a cold restart and try again",
    '相机存在启用中的 preload，尚未覆盖临时工作文件或开始恢复写入':
        "The camera has an active preload. The temporary work files are untouched and the restore hasn't started writing",
    '相机执行插件出现，已保存诊断，未覆盖工作文件': "The camera's run plugin appeared. Diagnostics saved; work files untouched",
    '相机临时状态仍在变化，已保存诊断，未覆盖工作文件：%s':
        "The camera's temporary state is still changing. Diagnostics saved; work files untouched: %s",
    '旧临时工作文件已保存诊断并清理；重新读取相机现况，直接按内建原厂基准生成恢复计划，不重放旧任务。':
        'Saved diagnostics for the old temporary work files and cleared them. Rereading the camera and planning the restore from the built-in factory data; the old job is not replayed.',
    '本地记录无法读取，未用于自动续接（记录保留）：%s':
        "This local record can't be read, so it is not resumed automatically (the record stays): %s",
    '恢复记录缺少机身身份，未用于自动续接（记录保留）：%s':
        'This restore record has no camera identity, so it is not resumed automatically (the record stays): %s',
    '有多台机身的未完成恢复记录（均保留）；本次按当前连接的相机重新生成恢复计划：%s':
        'Unfinished restore records exist for more than one camera (all kept). Planning the restore for the connected camera: %s',
    '程序窗口包含未确认的字节；保留记录，不能自动重放写入':
        'Program windows hold unconfirmed bytes. The record stays; the write cannot replay automatically',
    '临时文件和结果均缺失，尚无执行完成或新开机证据；不会重新写入，请保留事务记录':
        'The temporary files and the result are both missing, with no sign the run finished or the camera restarted. Nothing is rewritten; keep the transaction record',
    '执行插件仍存在，不能确认相机端已结束；不会删除或重试':
        "The run plugin is still present, so the camera side can't be confirmed finished. Nothing is deleted or retried",
    '相机端结果报告缺失，暂时不能确认执行结果；保留临时文件，未重新写入':
        "The camera's result report is missing, so the outcome can't be confirmed yet. Temporary files stay; nothing was rewritten",

    # looktool.namespause, portraitjob, verticalpersist
    '正在读取原程序，核对尚未写入的程序窗口。': 'Reading the original programs to check the program windows not yet written.',
    '名称完整读回：%d/%d': 'Names read back in full: %d/%d',
    '所有读写已结束。按弹窗完整断电重开后，检查横握／两侧竖握的 Fn 网格、创意外观选择页和参数调整页。':
        'All reads and writes are finished. After the cold restart in the dialog, check the Fn grid, the Creative Look list and its adjustment page, held level and upright both ways.',
    '当前内容已符合所选状态，没有重复写入。': 'The camera already matches the selected state; nothing was written again.',
    '竖屏开关和线框步骤已写好，继续安装其余所选功能。':
        'Vertical display switch and frames written. Installing the other selected features.',
    '请保留日志。下次点击同一操作会重新读取当前资源和机内撤销记录，不重放旧任务。':
        'Keep the log. Next time you click the same action, it rereads the current resources and the undo record on the camera; the old job is not replayed.',
    '恢复本测试版的原线框引用和资源索引。': "Restoring this test version's original frame references and resource index.",
    '竖屏资源处理已结束，仍需冷重开恢复 /usr 只读状态；不标记加载成功':
        'Vertical display resources are done, but /usr needs a cold restart to return to read-only. Not marked as loaded',
    '竖屏保存值已读取，但开机运行状态／资源尚不符合目标；不以 RAM 临时开启代替持久化验证':
        "Read the saved vertical display value, but the running state or resources don't match the target yet. A temporary switch-on in RAM doesn't count as saved",
    '线框资源已清理，但只读挂载仍忙；完整断电后再核对恢复':
        'Frame resources are cleared, but the read-only mount is still busy. Do a cold restart, then verify the restore',

    # camera_runtime.macos_host: taking USB over on macOS.
    '若相机屏幕询问 USB 连接方式，请选择第 2 项「影像传输（MSC）」。':
        'If the camera asks how to connect over USB, choose item 2, Mass Storage (MSC).',
    '请只连接一台海量存储模式的 A7C II，再准备 USB 连接。%s':
        'Connect one A7C II only, in Mass Storage mode, then prepare the USB connection. %s',
    '相机磁盘尚未稳定，尚未接管 USB。%s等存取灯停止后重试。':
        "The camera disk isn't settled yet, so USB wasn't taken over. %s Wait for the access lamp to stop, then try again.",
    '相机或磁盘在卸载前发生变化，尚未接管 USB。请重新连接后重试。':
        "Reconnect the camera and try again. The camera or its disk changed before unmounting, so USB wasn't taken over.",
    '正在卸载相机磁盘（不拔线）：%s': 'Unmounting the camera disk (leave the cable in): %s',
    '无法卸载相机存储卷。请关闭照片、图像捕捉及使用存储卡的程序后重试。':
        "Quit Photos, Image Capture and any app using the memory card, then try again. The camera volume couldn't be unmounted.",
    '相机存储卷未能全部卸载，尚未接管 USB。请关闭照片、图像捕捉及使用存储卡的程序后重试。':
        "Quit Photos, Image Capture and any app using the memory card, then try again. The camera volumes didn't all unmount, so USB wasn't taken over.",
    '服务模式已退出，等待普通 USB 连接（最多 %d 秒）。%s':
        'Service mode ended. Waiting up to %d seconds for the normal USB connection. %s',
    '等待普通 USB 重新枚举：%s': 'Waiting for normal USB to reappear: %s',
    '普通 USB 连接已恢复。': 'Normal USB connection is back.',
    '%d 秒内未恢复普通 USB 连接。下次操作前请在相机上选择「影像传输（MSC）」。':
        "The normal USB connection didn't come back within %d seconds. Before the next operation, choose Mass Storage (MSC) on the camera.",

    # camera_runtime.transport: the USB session.
    '相機操作超出有界等待時間': 'The camera operation ran past its time limit',
    '找不到 libusb 程式庫': "Can't find the libusb library",
    '需要且只能連接一台目標相機（USB %s）；請確認大量儲存模式及驅動':
        'Connect exactly one camera (USB %s). Check Mass Storage mode and the driver',
    '無法讀取 USB 配置': "Can't read the USB configuration",
    '等待相機完成 USB 初始化。': 'Waiting for the camera to finish USB start-up.',
    '相機正在準備機身資訊，稍候再讀取。': 'The camera is preparing its body information; reading again shortly.',
    '只支援 %s': 'Only the %s is supported',
    '服務備份缺少四位元組序列號屬性 00e70003': 'The service backup lacks the four-byte serial number property 00e70003',
    '等待相机从上一次服务模式恢复（%d 秒）。': 'Waiting for the camera to recover from the last service session (%d seconds).',
    '只读通信出错后，已让相机退出服务模式（未写入相机）。':
        'After the read error, the camera left service mode. Nothing was written to the camera.',
    '相机未能自动退出服务模式（%s）；请拔 USB、取电池约 1 分钟后重开。':
        "The camera didn't leave service mode by itself (%s). Unplug USB, take the battery out for about 1 minute, then turn the camera on.",
    '只支援 %s；USB 型號不符': "Only the %s is supported; the USB model doesn't match",
    '服务身份 0336 已出现，但接口无法打开；请保留驱动与 USB 日志，不重新认证。':
        "Service identity 0336 appeared, but its interface won't open. Keep the driver and USB logs; no new authentication.",
    '认证后相机未进入服务模式（期间出现的 Sony USB 身份：%s）。':
        "The camera didn't enter service mode after authentication (Sony USB identities seen: %s).",
    '无': 'none',
    '服務身份未出現；若是第一次，請依文件安裝0336驅動（已嘗試 %d 次）':
        "The service identity didn't appear. On a first connection, install the 0336 driver as the documentation describes (%d attempts made)",
    '服務身份未出現，相機也未回到普通 USB；請在相機選擇「影像傳輸（MSC）」後重新連接':
        "Choose Mass Storage (MSC) on the camera, then reconnect. The service identity didn't appear, and the camera didn't return to normal USB",
    '相机已回到普通 USB，冷却后自动重试（第 %d/%d 次）。':
        'The camera is back on normal USB. Retrying after a cool-down (attempt %d/%d).',
    '目前機身與備份機身不同': "This camera isn't the one the backup came from",
    '會話結果未知，停止後續命令': 'Session result unknown; stopping further commands',
    '不允許此 Jiritsu 命令': 'This Jiritsu command is not allowed',
    'Jiritsu 回應格式錯誤': 'Jiritsu response is malformed',
    'Jiritsu 狀態 %s': 'Jiritsu status %s',
    '路徑不符': "Path doesn't match",
    '不是指定臨時檔': 'Not one of the named temporary files',
    '臨時檔過大': 'Temporary file too large',
    '不允許空檔寫入': 'Writing an empty file is not allowed',
    '不允許此 CP 單元': 'This CP unit is not allowed',
    'CP 寫入目標或長度不符': "CP write target or length doesn't match",
    'AP 綁定目標或長度不符': "AP binding target or length doesn't match",

    # camera_runtime.core and compat: the FL2/FL3 program patch and its checks.
    '套件資產清單不符': "Package asset list doesn't match",
    '套件缺少檔案：%s': 'Package is missing a file: %s',
    '機身備份必須包含兩份校驗有效的 BK4': 'The camera backup must hold two BK4 files with valid checksums',
    '補丁窗口前置條件不符': "Patch window precondition doesn't hold",
    '補丁窗口重疊': 'Patch windows overlap',
    '候選檔長度被改動': 'Candidate file length changed',
    '%s 的執行期檢查位置已移動：appFw.so %s；沒有寫入': '%s moved a runtime check site: appFw.so %s; nothing written',
    '色彩單元長度不符': "Colour unit length doesn't match",
    '色彩映射不符': "Colour mapping doesn't match",
    '目標參數已使用，拒絕覆蓋': 'Target parameter in use; refusing to overwrite',
    '目標色彩槽已有其他參數引用': 'Another parameter already uses the target colour slot',
    '目標色彩槽已有資料': 'The target colour slot already holds data',
    '既有風格映射被改動': 'Existing style mapping changed',
    '既有色彩記錄被改動': 'Existing colour record changed',
    '既有矩陣被改動': 'Existing matrix changed',
    '設定項目集合改變': 'The set of settings changed',
    '目標設定讀回不符': "Target setting read-back doesn't match",
    '發現額外設定變動：chip%s/%s，請保存紀錄後檢查': 'Found an extra settings change: chip%s/%s. Save the record, then check it',
    '安裝器結果長度不符': "Installer result length doesn't match",
    '安裝器未完整成功；請勿重試或重新開機': "The installer didn't fully succeed. Don't retry or restart the camera",
    '寫入前完整檔案雜湊不符': "Whole-file hash before writing doesn't match",
    '寫入後完整檔案雜湊不符': "Whole-file hash after writing doesn't match",
    '只校驗模式出現非零寫入': 'Verify-only mode reported a non-zero write',
    '診斷結果過短': 'Diagnostic result too short',
    '型號欄位、權限或診斷結果不符': "Model field, permissions or diagnostic result doesn't match",
    '開機快照結果長度不符': "Boot snapshot result length doesn't match",
    '開機快照處理未驗證，請勿重複執行': "Boot snapshot handling isn't verified. Don't run it again",
    '不支援此開機快照起始狀態': 'This boot snapshot starting state is not supported',
    '開機快照寫入或讀回不完整': 'Boot snapshot write or read-back incomplete',
    '執行期結果長度不符': "Runtime result length doesn't match",
    '執行期身分／結果不符': "Runtime identity or result doesn't match",
    '未知原生模組': 'Unknown native module',
    '色彩記錄長度不符': "Colour record length doesn't match",
    '色彩記錄色度尾八項非零': 'Colour record chroma tail (last eight values) is not zero',
    '第 %s 個槽展開後行和不是 1024，拒絕寫入': 'Slot %s row sums are not 1024 once expanded; refusing to write',
    '色度不等於供體目標值': "Chroma doesn't equal the donor target",
    '矩陣不等於供體目標值（逐槽）': "Matrix doesn't equal the donor target (slot by slot)",
    '未知的色彩參數／槽組合，拒絕寫入': 'Unknown colour parameter and slot combination; refusing to write',
    '不驗證韌體來源。非本倉庫修改的韌體可能與 FL23 衝突，造成相機無法正常啟動；請保留備份。':
        "The firmware's origin isn't verified. Firmware changed by other projects may conflict with FL2/FL3 and stop the camera starting normally; keep a backup.",
    'LUT 相容模式缺少依賴，請更新完整工具並重新開啟 FL23.cmd。':
        'LUT compatibility mode is missing a dependency. Update to the complete tool and reopen FL23.cmd.',
    'FL23 只適用於 ILCE-7CM2 2.01；請依相機版本頁填寫':
        "FL2/FL3 works only on the ILCE-7CM2 with firmware 2.01. Enter the version shown on the camera's version page",
    'CP FL23 呼叫位置衝突：%s；沒有寫入': 'CP FL2/FL3 call site conflict: %s; nothing written',
    '補丁位置越界：%s %s': 'Patch offset out of range: %s %s',
    'CP FL23 原生曲線／模式位置衝突：%s': 'CP FL2/FL3 native curve or mode site conflict: %s',
    '補丁位置衝突：%s %s；沒有寫入；目前位元組(%s bytes, first 64)=%s。若使用過舊版本，請先依 README 恢復原廠功能後再安裝；保留本次日誌。':
        'Patch site conflict: %s %s; nothing written; current bytes (%s bytes, first 64)=%s. If you used an older version, run a factory restore (Factory restore page) as the README describes, then install again. Keep this log.',
    '完整還原候選不符': "Full-restore candidate doesn't match",
    '相容任務來源或目標已變': 'Compatibility job source or target changed',
    '相容候選已變': 'Compatibility candidate changed',
    '既有 FL23 色彩資料不完整；拒絕重寫': 'Existing FL2/FL3 colour data is incomplete; refusing to rewrite',

    # shutter_sound: the electronic shutter sound.
    '另一个声音操作仍在执行，请等它结束后再点击。': 'Another sound operation is still running. Click again when it finishes.',
    '使用本次选择替换声音；旧任务已归档，接下来读取相机现况，不重放旧命令。':
        'Replacing the sound with this selection. The old job is archived; reading the camera next. Old commands are not replayed.',
    '当前声音操作的机身绑定不一致': "This sound operation's camera binding doesn't match",
    '相机执行入口当前仍被占用，本次声音操作尚未开始。请等待正在执行的操作结束。':
        "Wait for the running operation to finish. The camera's run entry is busy, so this sound operation hasn't started.",
    '相机开始了另一项操作，本次声音替换尚未执行。': "The camera started another operation, so this sound replacement hasn't run.",
    '相机临时状态仍在变化，请等待当前操作结束。': "The camera's temporary state is still changing. Wait for the current operation to finish.",
    '当前声音临时文件替换未完成：%s': "The temporary sound file replacement didn't finish: %s",
    '旧自定义声音配置过大，无法作为本次替换的依据': 'The old custom sound settings are too large to base this replacement on',
    '旧自定义声音配置包含冲突的文件引用，请保留诊断包': 'The old custom sound settings hold conflicting file references. Keep the diagnostics',
    '旧自定义声音配置包含冲突的文件引用': 'The old custom sound settings hold conflicting file references',
    '现有声音标记无法对应到已完成的试听报告，已保存原标记；未覆盖未知运行任务。':
        "The current sound marker doesn't match a finished trial report. The marker is saved, and the unknown running task is left alone.",
    '当前相机的电子快门声音尚未开启，请先开启；本次没有注册试听声音。':
        'Turn on the electronic shutter sound first. It is off on this camera, so no trial sound was registered.',
    '请重新开启电子快门声以更新机械快门过滤，再进行试听；本次未注册声音。':
        'Turn on the electronic shutter sound again to update the mechanical shutter filter, then try the sound. No sound was registered.',
    '所选片段（起点 %.3f 秒，长度 %.3f 秒）几乎没有声音。很多音频开头是一段静音，请把起点移到声音出现的位置，或加长片段后重新转换。':
        'The clip (start %.3f s, length %.3f s) is almost silent. Many recordings open with silence: move the start to where the sound begins, or lengthen the clip, then convert again.',
    '电子快门声尚未开启。请先点击“开启电子快门声”，完成断电重开后再试听；本次没有写入固件或注册试听。':
        'Click "Turn on the electronic shutter sound" first, do the cold restart, then try the sound. It is off now; no firmware was written and no trial was registered.',
    '旧版快门声音尚未限制机械快门。请重新点击“开启电子快门声”更新后再试听；本次未注册声音。':
        'Click "Turn on the electronic shutter sound" again to update it, then try the sound. The older version still plays with the mechanical shutter. No sound was registered.',
    '未找到相机 USB 连接。请拔插 USB 并选择海量存储后重试；尚未进行服务认证或声音写入。':
        'Unplug and reconnect USB, choose Mass Storage, then try again. No camera USB connection was found; no service authentication or sound write took place.',
    '上一次声音操作（%s）中途停止，结果还没确认，所以没有开始新的操作，也没有连接相机。请点窗口底部“导出诊断包”发给作者核对；不要删除声音工作目录。（Previous operation is unresolved: %s）':
        'The last sound operation (%s) stopped partway and its result is unconfirmed, so nothing new started and the camera was not connected. Click "Export diagnostics…" at the bottom of the window and send the file to the author; keep the sound folder. (Previous operation is unresolved: %s)',
    '旧声音任务已确认停在写入前，检查结果和临时清理均完整；已解除占用，原日志保留。':
        'Confirmed the old sound job stopped before writing; its checks and temporary cleanup are complete. Released; the original log stays.',
    '上次保存停在电脑端准备阶段，未执行相机写入；已解除占用，保留原日志。':
        'The last save stopped while preparing on the computer; nothing was written to the camera. Released; the original log stays.',
    '上次试听在调用相机原生程序之前就已停止，没有注册任何声音；已解除占用，原记录保留。':
        "The last trial stopped before the camera's native program ran, so no sound was registered. Released; the original record stays.",
    '上次试听因旧标记在分配前停止，没有注册新声音；本次按当前状态新建试听。':
        'The last trial stopped at an old marker before allocation, so no new sound was registered. Starting a new trial from the current state.',
    '电子快门声已启用；已核对并接入声音工具，没有重复刷写。':
        'Electronic shutter sound is on. Checked and linked to the sound tools; nothing was rewritten.',
    '声音支援已准备，继续保存当前片段；全部写入结束后统一提示断电。':
        'Sound support is ready. Saving the clip next; the cold restart prompt comes once all writing is done.',
    '本次只接入已启用的声音开关，保持开机继续。': 'Using the sound switch already on. Keep the camera on and continue.',
    '请先转换所选片段，再调节音量。': 'Convert the clip first, then adjust the volume.',
    '请先点「转换所选片段」，转换成功后再试听。': 'Click "Convert the selected clip" first, and try the sound once it converts.',
    '试听结果已记录；可直接保存当前转换片段，无需先断电恢复。':
        'Trial result recorded. You can save the converted clip now; no cold restart needed first.',
    '自动准备电子快门声支援；已有开关直接接入，不要求先手动开启或关联旧任务。':
        'Preparing electronic shutter sound support. An existing switch is used as is; no need to turn it on first or link an old job.',
    '这个声音工作目录里没有可用的永久声音安装记录，本次没有连接相机。要还原相机的原厂快门音效，请点“恢复原厂功能”：它按相机当前字节还原全部声音程序，不依赖旧记录。':
        "This sound folder has no usable install record, so the camera was not connected. To get the factory shutter sound back, use the Factory restore page: it restores every sound program from the camera's current bytes, without old records.",
    '最近的声音安装记录不可直接恢复；改用同一机身最近一次完成的安装记录，从相机当前字节规划恢复。':
        "The latest sound install record can't be restored directly. Using this camera's last finished install record and planning the restore from its current bytes.",
    '\n电脑端音频处理失败，本次没有相机读写；请修正输入后重试。':
        '\nAudio processing failed on the computer; the camera was not read or written. Fix the input and try again.',
    '\n电脑端转换失败，本次没有相机读写；请修正输入后重新转换。':
        '\nConversion failed on the computer; the camera was not read or written. Fix the input and convert again.',

    # desktopapp.actions.recipe: a stopped recipe write, its error then the outcome hint.
    '%s 相机可能已执行、也可能未执行最后一次写入；请先重新读取相机，再做任何操作。':
        '%s The camera may or may not have applied the last write; read the camera again before anything else.',
    '%s 相机接受了最后一次写入，但没有生效。': '%s The camera accepted the last write but did not apply it.',
    '%s 相机拒绝了最后一次写入。': '%s The camera refused the last write.',
    '%s 最后一次写入没有发出。': '%s The last write was not sent.',

    # verticaltool.portraitworker
    '竖屏线框操作停止：文件 %d，步骤 %d，窗口 %d，错误 %d；已写 %d 字节。原生报告：%s':
        'Vertical display frame operation stopped: file %d, step %d, window %d, error %d; %d bytes written. Native report: %s',
}
