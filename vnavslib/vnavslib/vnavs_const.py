#
# From a user point of view, a mission is a sequence of operations to
# accomplish a goal or set of goal. It may include both autonomous and
# manual operations.
#
# Technically, the only absolute function of a mission is to log a sequence
# of messages. Everything else about the mission is determined by the mission
# file.
#

# This should be importable anywehre in vnavs, so it should only import system modules.
import configparser
import os
import sys

data_save_topic = "data/save"
data_get_topic = "data/get"
data_put_topic = "data/put"

mission_async_event_topic = "mission/async_event"
mission_load_topic = "mission/load"
mission_loaded_topic = "mission/loaded"
mission_cancel_topic = "mission/cancel"
mission_init_topic = "mission/init"
mission_end_topic = "mission/end"
mission_log_start_topic = "mission/log_start"
mission_log_stop_topic = "mission/log_stop"
mission_mark_topic = "mission/mark"
mission_paused_topic = "mission/paused"
mission_resume_topic = "mission/resume"
mission_stage_completed_topic = "mission/stage_completed"
mission_stage_started_topic = "mission/stage_started"
mission_sync_event_topic = "mission/sync_event"

system_abend_topic = "system/abend"
system_message_error_topic = "system/nak"
system_whoru = "system/whoru"  # fast mqtt server query
system_server = "system/server"  # fast mqtt server id

cameraman_mark_topic = "cameraman/mark"
cameraman_orders_topic = "cameraman/orders"
cameraman_pic_ready_topic = "cameraman/pic_ready"
cameraman_process_topic = "cameraman/process"

engineer_1_gps_topic = "engineer_1/gps"
engineer_1_imu_topic = "engineer_1/imu"
engineer_1_settings_topic = "engineer_1/settings"

helmsman_controls_topic = "helmsman/controls"
helmsman_orders_topic = "helmsman/orders"

navigator_service_topic = "navigator/service"
navigator_service_ack_topic = "navigator_service_ack"
navigator_mode_topic = "navigator/mode"
navigator_plot_topic = "navigator/plot"
navigator_waypoint_topic = "navigator/waypoint"

process_log_list_topic = "process/log_list"
process_clear_missions_topic = "process/clear_missions"
process_result_topic = "process/result"

stage_init = "init"
stage_finis = "finis"

DifferentialGpsClear = "clear"

config_file_path = os.path.expanduser("~/vnavs.ini")
FAST_MQTT_PORT = 4000
FILE_TRANSFER_PORT = 4010
ANY_HOST = ""  # for server, bind to all networks
DEFAULT_PORT = 3000
STANDARD_MQTT_PORT = 1883
VNAVS_IMAGES = "/exports/vnavs_images"
VNAVS_LOGS = "/exports/vnavs_logs"

HOST_LOCAL = "127.0.0.1"
GLOBAL_IP = "8.8.8.8"  # Google DNS resolver
NON_ROUTABLE_IP = "192.168.0.1"

ini_specs = {
    "Cameraman": {"ImageDir": VNAVS_IMAGES},
    "FileClient": {
        "Host": HOST_LOCAL,
        "Port": FILE_TRANSFER_PORT,
        "DownloadDir": "~/vnavs/download",
    },
    "FileServer": {
        "Host": ANY_HOST,
        "Port": FILE_TRANSFER_PORT,
        "xi": VNAVS_IMAGES,
        "xl": VNAVS_LOGS,
    },
    "MqttBroker": {"Host": HOST_LOCAL, "Port": STANDARD_MQTT_PORT},
    "MqttFast": {"Host": HOST_LOCAL, "Port": FAST_MQTT_PORT},
    "MqttFastServer": {
        "Host": ANY_HOST,
        "Port": FAST_MQTT_PORT,
        "ArchiveDir": VNAVS_LOGS,
    },
    "MissionControl": {"Scripts": "~/vnavs/scripts"},
    "Navigator": {"missiondir": "~/vnavs/missions"},
}


def CheckDirectory(dir_name, source, IsWriteable=True):
    expanded_dir_name = os.path.expanduser(dir_name)  # this expands tilde in path
    if not os.path.isdir(expanded_dir_name):
        raise ValueError(
            "Invalid directory path '{}' in {}".format(expanded_dir_name, source)
        )
    if IsWriteable:
        if not os.access(expanded_dir_name, os.W_OK):
            raise ValueError(
                "Directory path '{}' in {} is not writeable".format(
                    expanded_dir_name, source
                )
            )
    return expanded_dir_name


def UpdateIni(IniPath=config_file_path):
    config = configparser.ConfigParser()
    config.read(IniPath)
    for section_name, section_specs in ini_specs.items():
        for item_name, item_default in section_specs.items():
            try:
                current_value = config[section_name][item_name]
            except KeyError:
                if section_name not in config.sections():
                    config.add_section(section_name)
                config[section_name][item_name] = str(item_default)
            # print(section_name, item_name, current_value)
    with open(IniPath, "w") as configfile:
        config.write(configfile)


if __name__ == "__main__":
    if sys.argv[1] == "i":
        # UpdateIni(IniPath='test.ini')
        UpdateIni()
