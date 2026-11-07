import unittest
from unittest.mock import MagicMock, patch
import startup


class StartupChecks(unittest.TestCase):
    def test_frozen_command_quotes_path_and_runs_in_background(self):
        with patch.object(startup.sys, 'frozen', True, create=True), patch.object(startup.sys, 'executable', r'D:\My Tools\轻截\LightSnip.exe'):
            self.assertEqual(startup.startup_command(), '"D:\\My Tools\\轻截\\LightSnip.exe" --autostart')

    def test_source_command_uses_windowless_python_and_absolute_script(self):
        command=startup.startup_command()
        self.assertIn('pythonw.exe',command)
        self.assertIn(str(startup.Path(startup.__file__).with_name('app.py')),command)
        self.assertTrue(command.endswith(' --autostart'))

    def test_missing_registration_is_disabled(self):
        with patch.object(startup.winreg,'OpenKey',side_effect=FileNotFoundError):
            self.assertFalse(startup.is_enabled())

    def test_enable_and_disable_touch_only_own_current_user_value(self):
        registry=MagicMock()
        with patch.object(startup,'winreg',registry), patch.object(startup,'registered_command',return_value=''), patch.object(startup,'startup_command',return_value='"D:\\Tools\\LightSnip.exe" --autostart'):
            startup.set_enabled(True)
            registry.CreateKeyEx.assert_called_once_with(registry.HKEY_CURRENT_USER,startup.RUN_KEY,0,registry.KEY_SET_VALUE)
            registry.SetValueEx.assert_called_once_with(registry.CreateKeyEx.return_value.__enter__.return_value,'LightSnip',0,registry.REG_SZ,'"D:\\Tools\\LightSnip.exe" --autostart')
        registry.reset_mock()
        with patch.object(startup,'winreg',registry), patch.object(startup,'registered_command',return_value='old command'):
            startup.set_enabled(False)
            registry.DeleteValue.assert_called_once_with(registry.OpenKey.return_value.__enter__.return_value,'LightSnip')
            registry.DeleteKey.assert_not_called()

    def test_unchanged_registration_does_not_write(self):
        with patch.object(startup,'registered_command',return_value=''), patch.object(startup.winreg,'OpenKey') as opened:
            startup.set_enabled(False)
            opened.assert_not_called()

    def test_permission_error_is_reported_to_caller(self):
        with patch.object(startup,'registered_command',return_value=''), patch.object(startup.winreg,'CreateKeyEx',side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):startup.set_enabled(True)


if __name__=='__main__':
    unittest.main()
