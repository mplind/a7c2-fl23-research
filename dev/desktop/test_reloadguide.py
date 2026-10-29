"""Every completed cold-reload path gets guidance; temporary features stay on."""
import unittest

import pytest

from desktopapp import reloadguide


class ReloadGuideTests(unittest.TestCase):
    def test_all_completed_cold_reload_paths(self):
        cases = [('setup_all','WAIT_RELOAD'), ('direct_fl23_enable','AWAITING_RELOAD'),
            ('direct_fl23_disable','AWAITING_RELOAD'), ('direct_look_import','AWAITING_RELOAD'),
            ('direct_slot_default','AWAITING_RELOAD'), ('direct_factory_reset','AWAITING_RELOAD'),
            ('direct_resume_factory','AWAITING_RELOAD'), ('restore','RESTORED_AWAITING_RELOAD'),
            ('restore_auto','RESTORED_AWAITING_RELOAD'), ('look_install','AWAITING_RELOAD'),
            ('look_restore','RESTORED_AWAITING_RELOAD'), ('fl23_install','installed_pending_cold_start'),
            ('sound_on','written'), ('sound_off','restored'), ('sound_install','installed_cold_test_pending'),
            ('sound_restore_sound','restored_cold_test_pending')]
        cases += [('sound_confirm', phase) for phase in reloadguide.SOUND_PHASES['sound_confirm']]
        for action, phase in cases:
            with self.subTest(action=action, phase=phase):
                self.assertTrue(reloadguide.required(action, dict(phase=phase)))

    def test_no_cold_restart_before_audition_or_for_adoption_offline_and_failures(self):
        cases = [('sound_audition','temporary_pcm_registered_cold_reload_required_after_test'),
            ('sound_confirm_recovery','owner_confirmed_cold_recovered'), ('sound_import','converted_offline'),
            ('sound_verify','owner_confirmed_working'), ('vertical_enable','running'),
            ('direct_verify','LOADED'), ('direct_fl23_enable','LOADED'),
            ('direct_fl23_enable','PREFLIGHT_VERIFIED'), ('direct_fl23_enable','NEEDS_REVIEW'),
            ('sound_install','needs_review')]
        for action, phase in cases:
            with self.subTest(action=action):self.assertFalse(reloadguide.required(action, dict(phase=phase)))
        self.assertFalse(reloadguide.required('sound_on', dict(phase='written', adopted_existing_enabled=True)))

    def test_sound_confirmation_instructions_preserve_the_audition_sequence(self):
        text = reloadguide.text(mode='sound_confirm')
        self.assertIn('清除临时试听、恢复原声', text)
        self.assertIn('已断电恢复原声，记录恢复完成', text)
        self.assertIn('至少等待 1 分钟', text)

    def test_audition_popup_keeps_power_until_listening_not_cold_reload(self):
        result=dict(phase='temporary_pcm_registered_cold_reload_required_after_test')
        self.assertFalse(reloadguide.required('sound_audition',result))
        notice=reloadguide.sound_notice('sound_audition',result)
        for phrase in ('保持相机开机','不要关机','电子快门','确认试听正确','无需先恢复原声','保存当前自定义声音'):
            self.assertIn(phrase,notice['text'])
        self.assertIn('只关闭说明',notice['text'])

    def test_install_prerequisites_have_distinct_guidance_not_failure_or_fake_completion(self):
        for phase in ('sound_conversion_required',):
            notice=reloadguide.sound_notice('sound_install',dict(phase=phase))
            self.assertIn('保存尚未开始',notice['title'])
            self.assertIn('等待操作',notice['status'])
        notice=reloadguide.sound_notice('sound_confirm',dict(phase='owner_confirmed_audio_cold_reload_required'))
        self.assertIn('无需先断电或记录恢复',notice['text'])
        for phase in ('needs_review','installed_cold_test_pending'):
            self.assertIsNone(reloadguide.sound_notice('sound_install',dict(phase=phase)))


def test_setup_reload_names_continue_button():
    for mode in (None,'resource_reload'):
        message=reloadguide.text(setup=True,mode=mode)
        assert '继续安装' in message
        assert '继续上次安装' not in message
        assert '接回 USB' in message


# The next step after the cold restart matches what the job did: a feature turned off or a sound put
# back is checked as gone, never as there. The window passes the sound action, or the job's mode.
STEPS_EN = ('Only do this once the app shows "Reading and writing have ended".\n\n'
            '1. Unplug the USB cable and any other power.\n'
            '2. Wait for the access lamp to stop blinking. Don’t remove the battery while it blinks.\n'
            '3. Switch the camera OFF and wait until the screen and access lamp are dark.\n'
            '4. Take the battery out, so the camera has no battery, USB or other power, for at least 1 minute.\n'
            '5. Put the battery back and switch the camera on.')
OK_EN = '"OK" only closes these steps. It doesn’t power anything off or confirm the test for you.'
SOUND_CHECK = ('After switching on, shoot with the electronic shutter and check the sound, volume, shooting and '
               'playback. After saving a custom sound, you can verify it on the Shutter sound page.')
LOOKS_CHECK = ('Switch between ST and the changed slots and check that live view updates at once, then shoot and play '
               'back. A looks-only write needs no verify from the computer. If the name stage says programs aren’t '
               'written yet, reconnect and click "Continue changes…".')
NEXT_EN = {
    'fl23_enable': 'On the camera, check that FL2 and FL3 can be chosen, shot and played back. That’s all; no need to '
                   'reconnect and verify. For troubleshooting, see Troubleshooting on the FL2 / FL3 page.',
    'fl23_disable': 'On the camera, check that FL2 and FL3 are gone from the Creative Look list, that ST and your custom '
                    'looks still select, and that shooting and playback work. No need to reconnect and verify.',
    'sound_on': SOUND_CHECK,
    'sound_install': SOUND_CHECK,
    'sound_off': 'After switching on, take a shot with the electronic shutter and check that it is silent again, and '
                 'that shooting and playback work.',
    'sound_restore_sound': 'After switching on, take a shot with the electronic shutter and check that you hear the '
                           'camera’s own shutter sound, and that shooting and playback work. Your saved sound stays on '
                           'the camera, unused.',
    'vertical_disable': 'Vertical display turned off: the original frame references and resource index are back, and '
                        'helper aliases are removed. If the running firmware still uses appended images, a little image '
                        'tail data stays for now so the display doesn’t break; it doesn’t affect turning off and needs no '
                        'more clicks. After the restart, check the display held level and upright, and shooting.',
    'install_all': LOOKS_CHECK, 'look_import': LOOKS_CHECK, 'slot_default': LOOKS_CHECK,
    None: 'Check live view, menus and look previews, then shoot and play back. If this page shows a verify pending, '
          'reconnect USB and click the verify button it names.',
}
REASON_EN = {'fl23_enable': '\n\nTurning on FL2 and FL3 wrote program files. The restart after the earlier factory restore only '
                              'loaded the factory state; this change needs another cold restart.',
             'sound_on': '\n\nElectronic shutter sound turned on; it takes effect after the cold restart.',
             'sound_off': '\n\nElectronic shutter sound turned off; it takes effect after the cold restart.',
             'sound_restore_sound': '\n\nFactory shutter sound restored; it takes effect after the cold restart.'}
VERIFY_EN = 'Verifying only reads; it never writes again. '


@pytest.fixture
def english(monkeypatch):
    from desktopapp import i18n
    monkeypatch.setattr(i18n, '_language', 'en')


@pytest.mark.parametrize('mode', list(NEXT_EN), ids=[str(mode) for mode in NEXT_EN])
def test_each_modes_full_text_in_english(english, mode):
    verify = VERIFY_EN if mode in ('sound_on', 'sound_install') else ''
    expected = STEPS_EN + REASON_EN.get(mode, '') + '\n\nNext: ' + NEXT_EN[mode] + '\n\n' + verify + OK_EN
    assert reloadguide.text(mode=mode) == expected


@pytest.mark.parametrize('mode, removed', [
    ('sound_off', 'sound'), ('sound_restore_sound', 'saved sound'), ('fl23_disable', 'FL2'), ('vertical_disable', 'Vertical')])
def test_an_off_or_remove_mode_never_asks_to_check_what_it_removed(english, mode, removed):
    text = reloadguide.text(mode=mode)
    assert 'can be chosen' not in text and 'check the sound, volume' not in text and 'After saving a custom sound' not in text
    assert 'verify it on the Shutter sound page' not in text and VERIFY_EN not in text


@pytest.mark.parametrize('mode, chinese', [
    ('sound_off', '\n\n电子快门声已关闭，断电重开后生效。\n\n下一步：开机后用电子快门拍摄，确认电子快门已不再发声，拍摄及回放正常。\n\n'),
    ('sound_restore_sound', '\n\n已恢复原厂快门音效，断电重开后生效。\n\n下一步：开机后用电子快门拍摄，确认听到的是相机原来的快门声，'
                            '拍摄及回放正常。保存的自定义声音仍留在相机上，但不再使用。\n\n'),
    ('fl23_disable', '\n\n下一步：在相机中确认创意外观列表里已没有 FL2／FL3，ST 和自定义外观照常可选，拍摄及回放正常。'
                     '不必再接电脑点击核对。\n\n'),
], ids=['sound_off', 'sound_restore_sound', 'fl23_disable'])
def test_each_off_modes_full_text_in_chinese(mode, chinese):
    assert reloadguide.text(mode=mode) == reloadguide.STEPS + chinese + '点“确定”只关闭说明，不会自动断电或代替你确认测试。'
