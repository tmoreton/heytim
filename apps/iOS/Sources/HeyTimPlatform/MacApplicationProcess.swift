#if os(macOS)
  import AppKit
  import Darwin
  import Foundation

  enum MacApplicationProcess {
    static let maximumProcessCount = 4096

    struct Identity {
      let reportedPID: pid_t
      let bundleIdentifier: String
      let executableURL: URL
    }

    struct ProcessMetadata: Equatable {
      let pid: pid_t
      let uid: uid_t
      let realUID: uid_t
      let executableURL: URL
      let startSeconds: UInt64
      let startMicroseconds: UInt64
    }

    /// AppKit can report -1 for an otherwise running application. Resolve only
    /// an exact, live process belonging to this user; never infer identity by name.
    static func resolve(_ application: NSRunningApplication) -> pid_t? {
      guard !application.isTerminated,
        let bundleURL = application.bundleURL, bundleURL.isFileURL,
        let bundle = Bundle(url: bundleURL), let identifier = bundle.bundleIdentifier,
        let bundleExecutable = bundle.executableURL,
        let applicationIdentifier = application.bundleIdentifier,
        let applicationExecutable = application.executableURL
      else { return nil }
      return resolve(
        Identity(reportedPID: application.processIdentifier,
          bundleIdentifier: applicationIdentifier, executableURL: applicationExecutable),
        bundleIdentifier: identifier, bundleExecutableURL: bundleExecutable, currentUID: getuid(),
        listPIDs: { processIDs(for: getuid()) }, metadata: processMetadata)
    }

    static func resolve(
      _ application: Identity, bundleIdentifier: String, bundleExecutableURL: URL,
      currentUID: uid_t, listPIDs: () -> [pid_t]?, metadata: (pid_t) -> ProcessMetadata?
    ) -> pid_t? {
      guard !bundleIdentifier.isEmpty, application.bundleIdentifier == bundleIdentifier,
        let expected = canonicalPath(bundleExecutableURL),
        canonicalPath(application.executableURL) == expected
      else { return nil }
      func matches(_ process: ProcessMetadata, pid: pid_t) -> Bool {
        pid > 0 && process.pid == pid && process.uid == currentUID && process.realUID == currentUID
          && canonicalPath(process.executableURL) == expected
      }
      let candidate: ProcessMetadata
      if application.reportedPID > 0 {
        guard let process = metadata(application.reportedPID),
          matches(process, pid: application.reportedPID)
        else { return nil }
        candidate = process
      } else {
        guard let pids = listPIDs(), pids.count <= maximumProcessCount else { return nil }
        var matching: ProcessMetadata?
        for pid in Set(pids) where pid > 0 {
          // Unreadable metadata cannot establish that there is only one match.
          guard let process = metadata(pid) else { return nil }
          if matches(process, pid: pid) {
            guard matching == nil else { return nil }
            matching = process
          }
        }
        guard let process = matching else { return nil }
        candidate = process
      }
      // A PID may exit or be reused between enumeration and selection.
      guard let current = metadata(candidate.pid), current == candidate,
        matches(current, pid: candidate.pid)
      else { return nil }
      return candidate.pid
    }

    private static func canonicalPath(_ url: URL) -> String? {
      guard url.isFileURL else { return nil }
      return url.resolvingSymlinksInPath().standardizedFileURL.path
    }

    private static func processIDs(for uid: uid_t) -> [pid_t]? {
      let elementSize = MemoryLayout<pid_t>.size
      let needed = proc_listpids(UInt32(PROC_UID_ONLY), uid, nil, 0)
      guard needed > 0, Int(needed) <= maximumProcessCount * elementSize else { return nil }
      let capacity = min(maximumProcessCount, Int(needed) / elementSize + 32)
      var pids = [pid_t](repeating: 0, count: capacity)
      let filled = pids.withUnsafeMutableBytes {
        proc_listpids(UInt32(PROC_UID_ONLY), uid, $0.baseAddress, Int32($0.count))
      }
      // A full buffer could have omitted a second matching process.
      guard filled > 0, Int(filled) < capacity * elementSize,
        Int(filled).isMultiple(of: elementSize)
      else { return nil }
      return Array(pids.prefix(Int(filled) / elementSize).filter { $0 > 0 })
    }

    private static func processMetadata(_ pid: pid_t) -> ProcessMetadata? {
      guard pid > 0, let before = processInfo(pid) else { return nil }
      // PROC_PIDPATHINFO_MAXSIZE is 4 * MAXPATHLEN; that compound macro is not imported by Swift.
      var buffer = [CChar](repeating: 0, count: Int(PATH_MAX) * 4)
      let filled = buffer.withUnsafeMutableBytes {
        proc_pidpath(pid, $0.baseAddress, UInt32($0.count))
      }
      guard filled > 0, filled <= buffer.count,
        let terminator = buffer.firstIndex(of: 0), terminator > 0,
        let path = String(bytes: buffer[..<terminator].map { UInt8(bitPattern: $0) }, encoding: .utf8),
        let after = processInfo(pid),
        before.pbi_uid == after.pbi_uid, before.pbi_ruid == after.pbi_ruid,
        before.pbi_start_tvsec == after.pbi_start_tvsec,
        before.pbi_start_tvusec == after.pbi_start_tvusec
      else { return nil }
      return ProcessMetadata(
        pid: pid, uid: after.pbi_uid, realUID: after.pbi_ruid,
        executableURL: URL(fileURLWithPath: path).resolvingSymlinksInPath().standardizedFileURL,
        startSeconds: after.pbi_start_tvsec, startMicroseconds: after.pbi_start_tvusec)
    }

    private static func processInfo(_ pid: pid_t) -> proc_bsdinfo? {
      var value = proc_bsdinfo()
      let filled = withUnsafeMutablePointer(to: &value) {
        proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, $0, Int32(MemoryLayout<proc_bsdinfo>.size))
      }
      guard filled == MemoryLayout<proc_bsdinfo>.size, value.pbi_pid == UInt32(pid),
        value.pbi_status != SZOMB
      else { return nil }
      return value
    }
  }
#endif
