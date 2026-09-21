from environment.alarm import AlarmController
from environment.hardware.alarm_outputs import MockAlarmOutputDriver


def test_activating_alarm_turns_on_buzzer_and_led():
    driver = MockAlarmOutputDriver()
    controller = AlarmController(driver=driver)

    controller.set_alarm_active(True)

    assert driver.buzzer_on is True
    assert driver.led_on is True
    assert controller.is_alarm_active() is True


def test_deactivating_alarm_turns_off_buzzer_and_led():
    driver = MockAlarmOutputDriver()
    controller = AlarmController(driver=driver)
    controller.set_alarm_active(True)

    controller.set_alarm_active(False)

    assert driver.buzzer_on is False
    assert driver.led_on is False
    assert controller.is_alarm_active() is False


def test_set_alarm_active_is_idempotent():
    driver = MockAlarmOutputDriver()
    controller = AlarmController(driver=driver)

    controller.set_alarm_active(True)
    controller.set_alarm_active(True)

    assert driver.buzzer_on is True


def test_close_deenergizes_outputs():
    driver = MockAlarmOutputDriver()
    controller = AlarmController(driver=driver)
    controller.set_alarm_active(True)

    controller.close()

    assert driver.buzzer_on is False
    assert driver.led_on is False
