#include "controller_lock.hpp"
#include <cstdlib>
#include <iostream>
#include <sys/wait.h>

static void require(bool condition) {
    if (!condition) throw std::runtime_error("controller lock assertion failed");
}

int main() {
    char root[] = "/tmp/guidebot-lock-test-XXXXXX";
    require(mkdtemp(root) != nullptr);
    const std::string path = std::string(root) + "/controller.lock";
    const mode_t old_mask = umask(0077);
    {
        ControllerLock first(path.c_str());
        struct stat info{};
        require(stat(path.c_str(), &info) == 0);
        require((info.st_mode & 0777) == 0644);
        // An older controller's write-open and the new read-open share flock.
        const int legacy = open(path.c_str(), O_RDWR | O_CLOEXEC);
        require(legacy >= 0);
        require(flock(legacy, LOCK_EX | LOCK_NB) == -1);
        close(legacy);
        bool rejected = false;
        try { ControllerLock second(path.c_str()); }
        catch (const std::runtime_error& error) {
            rejected = std::string(error.what()).find("another motion library controller") != std::string::npos;
        }
        require(rejected);
    }
    umask(old_mask);
    {
        ControllerLock after_release(path.c_str());
    }
    // Existing read-only files work without changing their permissions/inode.
    require(chmod(path.c_str(), 0444) == 0);
    {
        ControllerLock read_only(path.c_str());
    }
    const std::string link = std::string(root) + "/symlink";
    require(symlink(path.c_str(), link.c_str()) == 0);
    bool rejected = false;
    try { ControllerLock invalid(link.c_str()); }
    catch (const std::runtime_error&) { rejected = true; }
    require(rejected);
    // Cross-account case when this test is run with root privileges.
    if (geteuid() == 0) {
        require(chmod(root, 0755) == 0);
        const pid_t child = fork();
        require(child >= 0);
        if (child == 0) {
            if (setgid(65534) || setuid(65534)) _exit(2);
            try { ControllerLock other_account(path.c_str()); }
            catch (...) { _exit(3); }
            _exit(0);
        }
        int status = 0;
        require(waitpid(child, &status, 0) == child);
        require(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    }
    unlink(link.c_str());
    unlink(path.c_str());
    rmdir(root);
    std::cout << "Controller lock permissions, exclusion, legacy compatibility and release passed.\n";
}
