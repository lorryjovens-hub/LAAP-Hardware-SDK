idf_component_register(
    SRCS
        "laap_core.c"
        "laap_protocol.c"
        "laap_transport.c"
        "laap_task.c"
    INCLUDE_DIRS "include"
    REQUIRES
        esp_websocket_client
        json
        esp_timer
        freertos
)
