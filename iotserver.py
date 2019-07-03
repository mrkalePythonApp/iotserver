#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Central IoT server hub and MQTT client.

Script provides following functionalities:

- Script acts as an MQTT client utilizing local MQTT broker ``mosquitto``
  for data exchange with outside environment.
- Script receives data from sensors managed by microcontrollers and process
  it and publishes it to cloud services.
- Script publishes received data and configuration data to the
  ``local MQTT broker``.
- Script sends commands through MQTT to microcontrollers in order to control
  them centrally.
- Script can receive commands through MQTT in order to change its behaviour
  during running.

"""
__version__ = '0.1.0'
__status__ = 'Alpha'
__author__ = 'Libor Gabaj'
__copyright__ = 'Copyright 2019, ' + __author__
__credits__ = [__author__]
__license__ = 'MIT'
__maintainer__ = __author__
__email__ = 'libor.gabaj@gmail.com'

# Standard library modules
import time
import os
import os.path
import sys
import argparse
import logging
import platform

# Third party modules
import gbj_pythonlib_sw.utils as modUtils
import gbj_pythonlib_sw.config as modConfig
import gbj_pythonlib_sw.mqtt as modMQTT
import gbj_pythonlib_sw.timer as modTimer
import gbj_pythonlib_iot.common as iot
import gbj_pythonlib_iot.system as iot_system


###############################################################################
# Enumeration and parameter classes
###############################################################################
class Script:
    """Script parameters."""

    (
        fullname, basename, name,
        running, service, lwt
    ) = (
            None, None, None,
            True, False, 'lwt',
        )


###############################################################################
# Script global variables
###############################################################################
cmdline = None  # Object with command line arguments
logger = None  # Object with standard logging
config = None  # Object with MQTT configuration file processing
mqtt = None  # Object for MQTT broker manipulation
# Devices
dev_system = None  # Object for processing system (microcomputer) parameters
dev_fan = None  # Object for processing cooling fan parameters


###############################################################################
# General actions
###############################################################################
def action_exit():
    """Perform all activities right before exiting the script."""
    modTimer.stop_timers()
    mqtt_publish_iot_lwt(iot.Status.OFFLINE)
    mqtt.disconnect()


###############################################################################
# MQTT actions
###############################################################################
def mqtt_reconnect():
    """Reconnect to MQTT broker if needed."""
    if mqtt.get_connected():
        return True


def mqtt_publish_iot_lwt(status):
    """Publish script status to the MQTT LWT topic."""
    if not mqtt.get_connected():
        return
    cfg_option = Script.lwt
    cfg_section = mqtt.GROUP_TOPICS
    message = iot.get_status(status)
    try:
        mqtt.publish(message, cfg_option, cfg_section)
        logger.debug(
            'Published to LWT MQTT topic %s: %s',
            mqtt.topic_name(cfg_option, cfg_section),
            message
        )
    except Exception as errmsg:
        logger.error(
            'Publishing %s to LWT MQTT topic %s failed: %s',
            message,
            mqtt.topic_name(cfg_option, cfg_section),
            errmsg,
        )


def mqtt_message_log(message):
    """Log receiving from an MQTT topic.

    Arguments
    ---------
    message : MQTTMessage object
        This is an object with members `topic`, `payload`, `qos`, `retain`.

    Returns
    -------
    bool
        Flag about present message payload.

    See Also
    --------
    gbj_pythonlib_sw.mqtt
        Module for MQTT processing.

    """
    if message.payload is None:
        payload = "None"
    else:
        payload = message.payload.decode('utf-8')
    logger.debug(
        '%s -- MQTT topic %s, QoS=%s, retain=%s: %s',
        sys._getframe(1).f_code.co_name,
        message.topic, message.qos, bool(message.retain), payload,
    )
    return message.payload is not None


###############################################################################
# Callback functions
###############################################################################
def cbTimer_mqtt_reconnect(*arg, **kwargs):
    """Execute MQTT reconnect."""
    if mqtt.get_connected():
        return
    logger.warning('Reconnecting to MQTT broker')
    try:
        mqtt.reconnect()
    except Exception as errmsg:
        logger.error(
            'Reconnection to MQTT broker failed with error: %s',
            errmsg)


def cbTimer_data(*arg, **kwargs):
    """Test data."""
    value = dev_system.get_temperature_current() or 0.0
    perc = dev_system.calculate_temperature_percentage(value) or 0.0
    logger.info(
        'System current temperature: %.1f°C (%.1f%%)',
        value,
        perc)
    value = dev_system.get_temperature_maximal() or 0.0
    logger.info('System maximal temperature: %.1f°C', value)


def cbMqtt_on_connect(client, userdata, flags, rc):
    """Process actions when the broker responds to a connection request.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    flags : dict
        Response flags sent by the MQTT broker.
    rc : int
        The connection result (result code).

    See Also
    --------
    gbj_pythonlib_sw.mqtt._on_connect()
        Description of callback arguments for proper utilizing.

    """
    if rc == 0:
        logger.debug('Connected to %s: %s', str(mqtt), userdata)
        setup_mqtt_filters()
        mqtt_publish_iot_lwt(iot.Status.ONLINE)
    else:
        logger.error('Connection to MQTT broker failed: %s (rc = %d)',
                     userdata, rc)


def cbMqtt_on_disconnect(client, userdata, rc):
    """Process actions when the client disconnects from the broker.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    rc : int
        The connection result (result code).

    See Also
    --------
    gbj_pythonlib_sw.mqtt._on_connect()
        Description of callback arguments for proper utilizing.

    """
    logger.warning('Disconnected from %s: %s (rc = %d)',
                   str(mqtt), userdata, rc)


def cbMqtt_on_subscribe(client, userdata, mid, granted_qos):
    """Process actions when the broker responds to a subscribe request.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    mid : int
        The message ID from the subscribe request.
    granted_qos : int
        The list of integers that give the QoS level the broker has granted
        for each of the different subscription requests.

    """
    pass


def cbMqtt_on_message(client, userdata, message):
    """Process actions when a non-filtered message has been received.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    message : MQTTMessage object
        The object with members `topic`, `payload`, `qos`, `retain`.

    Notes
    -----
    - The topic that the client subscribes to and the message does not match
      an existing topic filter callback.
    - Use message_callback_add() to define a callback that will be called for
      specific topic filters. This function serves as fallback when none
      topic filter matched.

    """
    if not mqtt_message_log(message):
        return


def cbMqtt_dev_system(client, userdata, message):
    """Process MQTT data related to microcomputer itself.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    message : MQTTMessage object
        The object with members `topic`, `payload`, `qos`, `retain`.

    """
    if not mqtt_message_log(message):
        return
    try:
        value = float(message.payload)
    except ValueError:
        logger.warning('Ignored wrong value: %s', message.payload)
        return
    # SoC temperature value in centigrades
    if message.topic == mqtt.topic_name('system_temp_cur_value'):
        dev_system.set_temperature_current(value)
    # SoC temperature percentage of maximal allowed temperature
    elif message.topic == mqtt.topic_name('system_temp_max_value'):
        dev_system.set_temperature_maximal(value)
    else:
        logger.debug(
            'Unexpected system topic "%s" with value: "%s"',
            message.topic,
            message.payload
        )


def cbMqtt_dev_fan(client, userdata, message):
    """Process MQTT data related to the cooling fan.

    Arguments
    ---------
    client : object
        MQTT client instance for this callback.
    userdata
        The private user data.
    message : MQTTMessage object
        The object with members `topic`, `payload`, `qos`, `retain`.

    """
    if not mqtt_message_log(message):
        return
    status = message.payload.decode('utf-8')
    try:
        value = float(message.payload)
    except ValueError:
        value = None
        return
    # Cooling fan status codes
    if message.topic == mqtt.topic_name('mqtt_topic_fan_status',
                                        mqtt.GROUP_DEFAULT):
        if status in iot.status_map:
            dev_fan.set_status(iot.get_status_index(status))
    # Status parameters
    elif message.topic == mqtt.topic_name('fan_status_percon') and value:
        value = dev_system.calculate_temperature_value(value)
        if value:
            dev_fan.set_temperature_on(value)
    elif message.topic == mqtt.topic_name('fan_status_percoff') and value:
        value = dev_system.calculate_temperature_value(value)
        if value:
            dev_fan.set_temperature_off(value)
    elif message.topic == mqtt.topic_name('fan_status_tempon') and value:
        dev_fan.set_temperature_on(value)
    elif message.topic == mqtt.topic_name('fan_status_tempoff') and value:
        dev_fan.set_temperature_off(value)
        pass
    # Unexpected status
    else:
        logger.debug(
            'Unexpected fan topic "%s" with value: "%s"',
            message.topic,
            message.payload
        )


###############################################################################
# Setup functions
###############################################################################
def setup_params():
    """Determine script operational parameters."""
    Script.fullname = os.path.splitext(os.path.abspath(__file__))[0]
    Script.basename = os.path.basename(__file__)
    Script.name = os.path.splitext(Script.basename)[0]
    Script.service = modUtils.check_service(Script.name)


def setup_cmdline():
    """Define command line arguments."""
    config_file = Script.fullname + '.ini'
    log_folder = 'x:/mqtt'
    # log_folder = '/var/log'

    parser = argparse.ArgumentParser(
        description='Central IoT server hub and MQTT client, version '
        + __version__
    )
    # Position arguments
    parser.add_argument(
        'config',
        type=argparse.FileType('r'),
        nargs='?',
        default=config_file,
        help='Configuration INI file, default: ' + config_file
    )
    # Options
    parser.add_argument(
        '-V', '--version',
        action='version',
        version=__version__,
        help='Current version of the script.'
    )
    parser.add_argument(
        '-v', '--verbose',
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        default='debug',
        help='Level of logging to the console.'
    )
    parser.add_argument(
        '-l', '--loglevel',
        choices=['debug', 'info', 'warning', 'error', 'critical'],
        default='debug',
        help='Level of logging to a log file.'
    )
    parser.add_argument(
        '-d', '--logdir',
        default=log_folder,
        help='Folder of a log file, default ' + log_folder
    )
    parser.add_argument(
        '-c', '--configuration',
        action='store_true',
        help='''Print configuration parameters in form of INI file content.'''
    )
    # Process command line arguments
    global cmdline
    cmdline = parser.parse_args()


def setup_logger():
    """Configure logging facility."""
    global logger
    # Set logging to file for module and script logging
    log_file = '/'.join([cmdline.logdir, Script.basename + '.log'])
    logging.basicConfig(
        level=getattr(logging, cmdline.loglevel.upper()),
        format='%(asctime)s - %(levelname)-8s - %(name)s: %(message)s',
        filename=log_file,
        filemode='w'
    )
    # Set console logging
    formatter = logging.Formatter(
        '%(levelname)-8s - %(name)-20s: %(message)s')
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, cmdline.verbose.upper()))
    console_handler.setFormatter(formatter)
    logger = logging.getLogger('{} {}'.format(Script.basename, __version__))
    logger.addHandler(console_handler)
    logger.info('Script started from file %s', os.path.abspath(__file__))


def setup_config():
    """Define configuration file management."""
    global config
    config = modConfig.Config(cmdline.config)


def setup_mqtt():
    """Define MQTT management."""
    global mqtt
    mqtt = modMQTT.MqttBroker(
        config,
        connect=cbMqtt_on_connect,
        disconnect=cbMqtt_on_disconnect,
        subscribe=cbMqtt_on_subscribe,
        message=cbMqtt_on_message,
    )
    # Last will and testament
    status = iot.get_status(iot.Status.OFFLINE)
    mqtt.lwt(status, Script.lwt, mqtt.GROUP_TOPICS)
    try:
        mqtt.connect(
            username=config.option('username', mqtt.GROUP_BROKER),
            password=config.option('password', mqtt.GROUP_BROKER),
        )
    except Exception as errmsg:
        logger.error(
            'Connection to MQTT broker failed with error: %s',
            errmsg)


def setup_mqtt_filters():
    """Define MQTT topic filters and subscribe to them.

    Notes
    -----
    - The function is called in 'on_connect' callback function after successful
      connection to an MQTT broker.

    """
    mqtt.callback_filters(
        filter_system=cbMqtt_dev_system,
        filter_fan=cbMqtt_dev_fan,
    )
    try:
        mqtt.subscribe_filters()
    except Exception as errcode:
        logger.error(
            'MQTT subscribtion to topic filters failed with error code %s',
            errcode)


def setup_timers():
    """Define dictionary of timers."""
    # Timer 01
    name = 'Timer_mqtt'
    cfg_section = 'TimerMqtt'
    # Reconnection period
    c_period = float(config.option('period_reconnect', cfg_section, 15.0))
    c_period = max(min(c_period, 180.0), 5.0)
    logger.debug('Setup timer %s: period = %ss', name, c_period)
    # Definition
    timer1 = modTimer.Timer(
        c_period,
        cbTimer_mqtt_reconnect,
        name=name,
        id=name,
    )
    modTimer.register_timer(name, timer1)
    # Timer 02
    name = 'Timer_data'
    # Reconnection period
    c_period = 5
    logger.debug('Setup timer %s: period = %ss', name, c_period)
    # Definition
    timer2 = modTimer.Timer(
        c_period,
        cbTimer_data,
        name=name,
        id=name,
    )
    modTimer.register_timer(name, timer1)
    modTimer.register_timer(name, timer2)
    # Start all timers
    modTimer.start_timers()


def setup():
    """Global initialization."""
    # Print configuration file to the console
    if cmdline.configuration:
        print(config.get_content())
    # Running mode
    if Script.service:
        logger.info('Script runs as the service %s.service', Script.name)
    else:
        logger.info('Script %s runs in standalone mode', Script.name)
    # Devices initiation
    global dev_system
    dev_system = iot_system.System()


def loop():
    """Wait for keyboard or system exit."""
    try:
        logger.info('Script loop started')
        while (Script.running):
            time.sleep(0.01)
        logger.info('Script finished')
    except (KeyboardInterrupt, SystemExit):
        logger.info('Script cancelled from keyboard')
    finally:
        action_exit()


def main():
    """Fundamental control function."""
    setup_params()
    setup_cmdline()
    setup_logger()
    setup_config()
    setup_mqtt()
    setup_timers()
    setup()
    loop()


if __name__ == "__main__":
    if platform.system() == 'Linux' and os.getegid() != 0:
        sys.exit('Script must be run as root')
    main()
