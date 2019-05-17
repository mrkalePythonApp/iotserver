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
__version__ = "0.1.0"
__status__ = "Alpha"
__author__ = "Libor Gabaj"
__copyright__ = "Copyright 2019, " + __author__
__credits__ = [__author__]
__license__ = "MIT"
__maintainer__ = __author__
__email__ = "libor.gabaj@gmail.com"

# Standard library modules
import time
import os
import os.path
import sys
import argparse
import logging
import psutil
# Third party modules
import gbj_pythonlib_sw.config as modConfig
import gbj_pythonlib_sw.mqtt as modMQTT
import gbj_pythonlib_sw.timer as modTimer


###############################################################################
# Enumeration and parameter classes
###############################################################################
class Action:
    """Enumeration of possible actions to be performed."""

    (
        PARAMS_RESET, GET_STATUS, SCRIPT_EXIT,
    ) = range(3)


class IoT:
    """Data related to IoT server."""

    (
        LWT, ONLINE, OFFLINE,
    ) = (
            "lwt_iot", "Online", "Offline",
        )


class Fan:
    """Data related to cooling fan."""

    (
        LWT, ONLINE, OFFLINE,
        RUNNING, IDLE,
        CMD_STATUS,
    ) = (
            "lwt_fan", "Online", "Offline",
            "Running", "Idle",
            "STATUS",
        )


###############################################################################
# Mapping commands to actions and vice-versa
###############################################################################
map_command = {
    "STATUS": Action.GET_STATUS,
    "EXIT": Action.SCRIPT_EXIT,
}


###############################################################################
# Script global variables
###############################################################################
script_run = True  # Flag about running script in a loop
cmdline = None  # Object with command line arguments
logger = None  # Object with standard logging
config = None  # Object with MQTT configuration file processing
mqtt = None  # Object for MQTT broker manipulation

script_pathname = ''  # Name of this script including full path
script_basename = ''  # Name of this script excluding path but with extension
script_name = ''  # Bare name of this script
service_flag = False  # Flag determining running script as a service


###############################################################################
# Helper functions
###############################################################################
def check_service():
    """Detect running script as a service.

    Returns
    -------
    bool
        Flag about running script as a service.

    """
    ls = []
    for p in psutil.process_iter(attrs=['name']):
        if p.info['name'] == script_name:
            ls.append(p)
    return len(ls) > 0


###############################################################################
# General actions
###############################################################################
def action_exit():
    """Perform all activities right before exiting the script."""
    mqtt.disconnect()


def action_iot(action, value=None):
    """Perform action for the IoT server.

    Arguments
    ---------
    action : str
        Action name to be realized.
    value
        Any value that the action should be realized with.

    """
    # Cancel script
    if action == Action.SCRIPT_EXIT:
        if service_flag:
            logger.warning("Exiting the script in service mode is prohibited")
        else:
            logger.warning("Stop script")
            global script_run
            script_run = False


###############################################################################
# MQTT actions
###############################################################################
def mqtt_reconnect():
    """Reconnect to MQTT broker if needed."""
    if mqtt.get_connected():
        return True


def mqtt_publish_iot_lwt_online():
    """Publish IoTn online status to the MQTT LWT topic."""
    if not mqtt.get_connected():
        return
    cfg_option = IoT.LWT
    cfg_section = mqtt.GROUP_TOPICS
    message = IoT.ONLINE
    try:
        mqtt.publish(message, cfg_option, cfg_section)
        logger.debug(
            "Published LWT %s to MQTT topic %s",
            message, mqtt.topic_name(cfg_option, cfg_section),
        )
    except Exception as errmsg:
        logger.error(
            "Publishing LWT %s to MQTT topic %s failed: %s",
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
    logger.debug(
        "Message from MQTT topic %s with qos %s and retain %s",
        message.topic, message.qos, message.retain)
    if message.payload is None:
        return False
    logger.debug("%s: %s", sys._getframe(1).f_code.co_name,
                 message.payload.decode("utf-8"))
    return True


###############################################################################
# Callback functions
###############################################################################
def cbTimer_mqtt_reconnect(*arg, **kwargs):
    """Execute MQTT reconnect."""
    if mqtt.get_connected():
        return
    logger.warning("Reconnecting to MQTT broker")
    try:
        mqtt.reconnect()
    except Exception as errmsg:
        logger.error(
            "Reconnection to MQTT broker failed with error: %s",
            errmsg)


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
        logger.debug("Connected to %s: %s", str(mqtt), userdata)
        setup_mqtt_filters()
        mqtt_publish_iot_lwt_online()
    else:
        logger.error("Connection to MQTT broker failed: %s (rc = %d)",
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
    logger.warning("Disconnected from %s: %s (rc = %d)",
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


def cbMqtt_on_message_data(client, userdata, message):
    """Process received data from MQTT topics.

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
    # Server temperature value
    if message.topic == mqtt.topic_name("server_temp_value"):
        value = float(message.payload)
        logger.debug("Received server temperature value %s°C", value)
    # Server temperature percentage
    elif message.topic == mqtt.topic_name("server_temp_percentage"):
        value = float(message.payload)
        logger.debug("Received server temperature percentage %s°C", value)
    # Unexpected data
    else:
        logger.warning(
            "Received unknown data %s from topic %s",
            message.payload.decode("utf-8"), message.topic)


def cbMqtt_on_message_command(client, userdata, message):
    """Process command at receiving a message from the command topic(s).

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
    - The topic that the client subscribes to and the message match the topic
      filter for server commands.

    """
    if not mqtt_message_log(message):
        return
    command = message.payload.decode("utf-8")
    if message.topic == mqtt.topic_name("fan_command_control"):
        logger.debug(
            "Received IoT command %s from topic %s",
            command, message.topic)
        action_iot(map_command[command])
    # Unexpected command
    else:
        logger.warning(
            "Received unknown command %s from topic %s",
            message.payload.decode("utf-8"), message.topic)


###############################################################################
# Setup functions
###############################################################################
def setup_params():
    """Determine script operational parameters."""
    global script_fullname, script_basename, script_name, service_flag
    script_fullname = os.path.splitext(os.path.abspath(__file__))[0]
    script_basename = os.path.basename(__file__)
    script_name = os.path.splitext(script_basename)[0]
    service_flag = check_service()


def setup_cmdline():
    """Define command line arguments."""
    config_file = script_fullname + ".ini"
    log_folder = "/var/log"

    parser = argparse.ArgumentParser(
        description="Central IoT server hub and MQTT client, version "
        + __version__
    )
    # Position arguments
    parser.add_argument(
        "config",
        type=argparse.FileType("r"),
        nargs="?",
        default=config_file,
        help="Configuration INI file, default: " + config_file
    )
    # Options
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=__version__,
        help="Current version of the script."
    )
    parser.add_argument(
        "-v", "--verbose",
        choices=["debug", "info", "warning", "error", "critical"],
        default="warning",
        help="Level of logging to the console."
    )
    parser.add_argument(
        "-l", "--loglevel",
        choices=["debug", "info", "warning", "error", "critical"],
        default="debug",
        help="Level of logging to a log file."
    )
    parser.add_argument(
        "-d", "--logdir",
        default=log_folder,
        help="Folder of a log file, default " + log_folder
    )
    parser.add_argument(
        "-c", "--configuration",
        action="store_true",
        help="""Print configuration parameters in form of INI file content."""
    )
    # Process command line arguments
    global cmdline
    cmdline = parser.parse_args()


def setup_logger():
    """Configure logging facility."""
    global logger
    # Set logging to file for module and script logging
    log_file = "/".join([cmdline.logdir, script_basename + ".log"])
    logging.basicConfig(
        level=getattr(logging, cmdline.loglevel.upper()),
        format="%(asctime)s - %(levelname)-8s - %(name)s: %(message)s",
        filename=log_file,
        filemode="w"
    )
    # Set console logging
    formatter = logging.Formatter(
        "%(levelname)-8s - %(name)-20s: %(message)s")
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, cmdline.verbose.upper()))
    console_handler.setFormatter(formatter)
    logger = logging.getLogger("{} {}".format(script_basename, __version__))
    logger.addHandler(console_handler)
    logger.info("Script started from file %s", os.path.abspath(__file__))


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
    mqtt.lwt(IoT.OFFLINE, IoT.LWT, mqtt.GROUP_TOPICS)
    try:
        mqtt.connect(
            username=config.option("username", mqtt.GROUP_BROKER),
            password=config.option("password", mqtt.GROUP_BROKER),
        )
    except Exception as errmsg:
        logger.error(
            "Connection to MQTT broker failed with error: %s",
            errmsg)


def setup_mqtt_filters():
    """Define MQTT topic filters and subscribe to them.

    Notes
    -----
    - The function is called in 'on_connect' callback function after successful
      connection to an MQTT broker.

    """
    mqtt.callback_filters(
        iot_filter_command=cbMqtt_on_message_command,
        server_temp=cbMqtt_on_message_data,
    )
    try:
        mqtt.subscribe_filters()
    except Exception as errcode:
        logger.error(
            "MQTT subscribtion to topic filters failed with error code %s",
            errcode)


def setup_timers():
    """Define dictionary of timers."""
    # Timer 01
    name = "Timer_mqtt"
    cfg_section = "TimerMqtt"
    # Reconnection period
    c_period = float(config.option("period_reconnect", cfg_section, 15.0))
    c_period = max(min(c_period, 180.0), 5.0)
    logger.debug("Setup timer %s: period = %ss", name, c_period)
    # Definition
    timer1 = modTimer.Timer(
        c_period,
        cbTimer_mqtt_reconnect,
        name=name,
        id=name,
    )
    modTimer.register_timer(name, timer1)
    # Start all timers
    modTimer.start_timers()


def setup():
    """Global initialization."""
    # Print configuration file to the console
    if cmdline.configuration:
        print(config.get_content())
    # Running mode
    if service_flag:
        logger.info("Script runs as the service %s.service", script_name)
    else:
        logger.info("Script %s runs in standalone mode", script_name)


def loop():
    """Wait for keyboard or system exit."""
    try:
        logger.info("Script loop started")
        while (script_run):
            time.sleep(0.01)
        logger.info("Script finished")
    except (KeyboardInterrupt, SystemExit):
        logger.info("Script cancelled from keyboard")
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
    if os.getegid() != 0:
        sys.exit('Script must be run as root')
    main()
