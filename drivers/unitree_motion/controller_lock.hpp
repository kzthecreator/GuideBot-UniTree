#pragma once

#include <cerrno>
#include <cstring>
#include <stdexcept>
#include <string>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

// Keep a single shared inode across accounts and across old/new controllers.
// Linux flock(LOCK_EX) supports read-only descriptors; O_CREAT on an existing
// foreign-owned /tmp file can be rejected by fs.protected_regular, so open it
// without O_CREAT first. Never unlink the lock to repair permission problems.
class ControllerLock {
public:
    explicit ControllerLock(const char* path = "/tmp/g1_arm_motion_library.lock") {
        const int flags = O_RDONLY | O_CLOEXEC | O_NOFOLLOW;
        fd_ = open(path, flags);
        if (fd_ < 0 && errno == ENOENT) {
            fd_ = open(path, flags | O_CREAT | O_EXCL, 0644);
            if (fd_ >= 0) {
                if (fchmod(fd_, 0644) != 0) fail("cannot set controller lock permissions", path);
            } else if (errno == EEXIST) {
                fd_ = open(path, flags);
            }
        }
        if (fd_ < 0) fail("cannot open motion controller lock", path);
        struct stat info{};
        if (fstat(fd_, &info) != 0) fail("cannot inspect motion controller lock", path);
        if (!S_ISREG(info.st_mode) || info.st_nlink != 1) {
            close(fd_); fd_ = -1;
            throw std::runtime_error("motion controller lock must be one regular file");
        }
        if (flock(fd_, LOCK_EX | LOCK_NB) != 0) {
            const int error = errno;
            close(fd_); fd_ = -1;
            if (error == EWOULDBLOCK || error == EAGAIN)
                throw std::runtime_error("another motion library controller is running");
            throw std::runtime_error(std::string("cannot acquire motion controller lock: ") + std::strerror(error));
        }
    }

    ~ControllerLock() { if (fd_ >= 0) close(fd_); }
    ControllerLock(const ControllerLock&) = delete;
    ControllerLock& operator=(const ControllerLock&) = delete;

private:
    int fd_ = -1;
    void fail(const char* message, const char* path) {
        const int error = errno;
        if (fd_ >= 0) close(fd_);
        fd_ = -1;
        throw std::runtime_error(std::string(message) + ": " + path + ": " + std::strerror(error));
    }
};
