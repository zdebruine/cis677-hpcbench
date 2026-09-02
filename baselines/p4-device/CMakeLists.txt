cmake_minimum_required(VERSION 3.16)
project(cis677_p4 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()
set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -DNDEBUG")
find_package(OpenMP)

add_executable(prepare  src/prepare.cpp)
add_executable(solution src/solution.cpp)
foreach(t prepare solution)
  target_include_directories(${t} PRIVATE ${CMAKE_SOURCE_DIR}/include)
  if(OpenMP_CXX_FOUND)
    target_link_libraries(${t} PRIVATE OpenMP::OpenMP_CXX)
  endif()
endforeach()

# ---- optional CUDA -----------------------------------------------------
# Students enable this. The shipped CPU baseline builds without a GPU, which
# is what lets the reference digest be generated anywhere.
include(CheckLanguage)
check_language(CUDA)
if(CMAKE_CUDA_COMPILER AND EXISTS ${CMAKE_SOURCE_DIR}/src/kernels.cu)
  enable_language(CUDA)
  set(CMAKE_CUDA_ARCHITECTURES 90)          # H100 NVL
  target_sources(solution PRIVATE src/kernels.cu)
  target_compile_definitions(solution PRIVATE HPCBENCH_CUDA=1)
  target_link_libraries(solution PRIVATE cublas cusparse)
  message(STATUS "CUDA enabled: building GPU path (sm_90)")
else()
  message(STATUS "No CUDA or no src/kernels.cu -- CPU path only")
endif()
