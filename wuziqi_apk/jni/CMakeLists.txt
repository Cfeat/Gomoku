# Build Rapfi + JNI wrapper as a shared library for Android
cmake_minimum_required(VERSION 3.18)
project(rapfi-jni)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Rapfi sources (same as original CMakeLists.txt)
set(RAPFI_DIR "../rapfi/Rapfi")

set(CORE_SOURCES
    ${RAPFI_DIR}/command/argutils.cpp
    ${RAPFI_DIR}/command/benchmark.cpp
    ${RAPFI_DIR}/command/command.cpp
    ${RAPFI_DIR}/command/gomocup.cpp
    ${RAPFI_DIR}/core/hash.cpp
    ${RAPFI_DIR}/core/iohelper.cpp
    ${RAPFI_DIR}/core/utils.cpp
    ${RAPFI_DIR}/core/platform.cpp
    ${RAPFI_DIR}/core/version.cpp
    ${RAPFI_DIR}/database/dbclient.cpp
    ${RAPFI_DIR}/database/dbutils.cpp
    ${RAPFI_DIR}/database/dbtypes.cpp
    ${RAPFI_DIR}/database/yxdbstorage.cpp
    ${RAPFI_DIR}/eval/eval.cpp
    ${RAPFI_DIR}/eval/evaluator.cpp
    ${RAPFI_DIR}/eval/mix9svqnnue.cpp
    ${RAPFI_DIR}/eval/mix10nnue.cpp
    ${RAPFI_DIR}/game/board.cpp
    ${RAPFI_DIR}/game/movegen.cpp
    ${RAPFI_DIR}/game/pattern.cpp
    ${RAPFI_DIR}/search/hashtable.cpp
    ${RAPFI_DIR}/search/movepick.cpp
    ${RAPFI_DIR}/search/opening.cpp
    ${RAPFI_DIR}/search/searchcommon.cpp
    ${RAPFI_DIR}/search/searchoutput.cpp
    ${RAPFI_DIR}/search/searchthread.cpp
    ${RAPFI_DIR}/search/timecontrol.cpp
    ${RAPFI_DIR}/search/ab/history.cpp
    ${RAPFI_DIR}/search/ab/search.cpp
    ${RAPFI_DIR}/search/mcts/node.cpp
    ${RAPFI_DIR}/search/mcts/search.cpp
    ${RAPFI_DIR}/config.cpp
    ${RAPFI_DIR}/internalConfig.cpp
    ${RAPFI_DIR}/main.cpp
    ${RAPFI_DIR}/external/lz4/src/lz4_all.c
    ${RAPFI_DIR}/external/lz4/src/xxhash.c
)

# JNI wrapper
list(APPEND CORE_SOURCES engine_jni.cpp)

# Build as shared library
add_library(rapfi SHARED ${CORE_SOURCES})

target_include_directories(rapfi PRIVATE
    ${RAPFI_DIR}
    ${RAPFI_DIR}/command
    ${RAPFI_DIR}/core
    ${RAPFI_DIR}/database
    ${RAPFI_DIR}/eval
    ${RAPFI_DIR}/game
    ${RAPFI_DIR}/search
    ${RAPFI_DIR}/search/ab
    ${RAPFI_DIR}/search/mcts
    ${RAPFI_DIR}/tuning
    ${RAPFI_DIR}/external/lz4/include
    ${RAPFI_DIR}/external/simde/include
    ${RAPFI_DIR}/external/cpptoml/include
    ${RAPFI_DIR}/external/cxxopts/include
)

if(NO_COMMAND_MODULES)
    target_compile_definitions(rapfi PRIVATE NO_COMMAND_MODULES=1)
endif()

if(ANDROID)
    target_compile_definitions(rapfi PRIVATE ANDROID)
    target_link_libraries(rapfi PRIVATE atomic)
else()
    target_link_libraries(rapfi PRIVATE pthread atomic)
endif()
