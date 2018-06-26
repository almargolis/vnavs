#
# From a user point of view, a mission is a sequence of operations to
# accomplish a goal or set of goal. It may include both autonomous and
# manual operations.
#
# Technically, the only absolute function of a mission is to log a sequence
# of messages. Everything else about the mission is determined by the mission
# file.
#

data_save_topic = 'data/save'
data_get_topic = 'data/get'

mission_async_event_topic = 'mission/async_event'
mission_load_topic = 'mission/load'
mission_cancel_topic = 'mission/cancel'
mission_init_topic = 'mission/init'
mission_end_topic = 'mission/end'
mission_log_start_topic = 'mission/log_start'
mission_log_stop_topic = 'mission/log_stop'
mission_mark_topic = 'mission/mark'
mission_paused_topic = 'mission/paused'
mission_resume_topic = 'mission/resume'
mission_stage_completed_topic = 'mission/stage_completed'
mission_stage_started_topic = 'mission/stage_started'
mission_sync_event_topic = 'mission/sync_event'

system_abend_topic = 'system/abend'
system_message_error_topic = 'system/nak'

cameraman_mark_topic = 'cameraman/mark'
cameraman_orders_topic = 'cameraman/orders'
cameraman_pic_ready_topic = 'cameraman/pic_ready'
cameraman_process_topic = 'cameraman/process'

engineer_1_gps_topic = 'engineer_1/gps'
engineer_1_imu_topic = 'engineer_1/imu'

helmsman_controls_topic = 'helmsman/controls'
helmsman_orders_topic = 'helmsman/orders'

navigator_service_topic = 'navigator/service'
navigator_service_ack_topic = 'navigator_service_ack'
navigator_mode_topic = 'navigator/mode'
navigator_plot_topic = 'navigator/plot'
navigator_waypoint_topic = 'navigator/waypoint'

process_log_list_topic = 'process/log_list'
process_clear_missions_topic = 'process/clear_missions'
process_result_topic = 'process/result'

stage_init = 'init'
stage_finis = 'finis'

dname_field_name = '_dname_'
dtype_field_name = '_dtype_'

