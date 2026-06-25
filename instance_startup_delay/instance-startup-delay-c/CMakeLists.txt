cmake_minimum_required(VERSION 3.5)

project(startup-delay-demo-service C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_INSTALL_PREFIX "${CMAKE_SOURCE_DIR}")

add_executable(${PROJECT_NAME}
    src/main.c
)

install(TARGETS ${PROJECT_NAME} RUNTIME DESTINATION rootfs)
