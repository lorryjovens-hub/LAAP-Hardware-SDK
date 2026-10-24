idf_component_register(
    SRCS
        "lbp_frame.c"
        "lbp_payload.c"
        "lbp_tp.c"
        "lbp_bus.c"
        "lbp_node.c"
        "lbp_master.c"
        "lbp_bmd_presets.c"
    INCLUDE_DIRS "include"
    REQUIRES
        driver
        esp_timer
        freertos
)

