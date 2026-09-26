#if os(iOS)
  import Foundation
  import HealthKit
  import Observation

  @MainActor @Observable
  final class AppleHealthCoordinator {
    static let enabledBotIDsKey = "heytim.apple-health.bot-ids"
    static let permissionRequestedKey = "heytim.apple-health.permission-requested"

    private let store = HKHealthStore()
    private(set) var enabledBotIDs = Set(
      UserDefaults.standard.stringArray(forKey: enabledBotIDsKey) ?? [])
    private(set) var permissionRequested = UserDefaults.standard.bool(
      forKey: permissionRequestedKey)
    private(set) var errorMessage: String?

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

    func isEnabled(for botID: String) -> Bool {
      enabledBotIDs.contains(botID)
    }

    @discardableResult
    func setEnabled(_ enabled: Bool, for botID: String) async -> Bool {
      if enabled {
        guard await requestReadAccess() else { return false }
        enabledBotIDs.insert(botID)
      } else {
        enabledBotIDs.remove(botID)
      }
      UserDefaults.standard.set(enabledBotIDs.sorted(), forKey: Self.enabledBotIDsKey)
      return true
    }

    @discardableResult
    func requestReadAccess() async -> Bool {
      guard isAvailable else {
        errorMessage = "Apple Health data is not available on this device."
        return false
      }
      do {
        try await store.requestAuthorization(toShare: [], read: Self.readTypes)
        permissionRequested = true
        UserDefaults.standard.set(true, forKey: Self.permissionRequestedKey)
        errorMessage = nil
        return true
      } catch {
        errorMessage = error.localizedDescription
        return false
      }
    }

    func execute(_ call: DeviceCall) async -> DeviceCallOutcome {
      guard call.toolId == "apple_health", isEnabled(for: call.botId) else {
        return .failure("Apple Health access is not enabled for this bot on this iPhone.")
      }
      guard isAvailable else {
        return .failure("Apple Health data is not available on this iPhone.")
      }
      do {
        switch call.operation {
        case "apple_health_activity_summary":
          return .success(try await activitySummary(days: integer(call, "days", 7, 1...31)))
        case "apple_health_workouts":
          return .success(
            try await workoutSummary(
              days: integer(call, "days", 30, 1...90),
              activity: string(call, "activity", "all"),
              limit: integer(call, "limit", 20, 1...50)))
        case "apple_health_running_totals":
          return .success(try await runningTotals(days: integer(call, "days", 90, 1...180)))
        case "apple_health_steps":
          return .success(try await stepSummary(days: integer(call, "days", 7, 1...31)))
        default:
          return .failure("This Apple Health operation is not supported by this app version.")
        }
      } catch {
        return .failure("Apple Health could not complete the request: \(error.localizedDescription)")
      }
    }

    private static var readTypes: Set<HKObjectType> {
      var values: Set<HKObjectType> = [HKObjectType.workoutType()]
      values.insert(HKObjectType.activitySummaryType())
      if let steps = HKObjectType.quantityType(forIdentifier: .stepCount) {
        values.insert(steps)
      }
      if let distance = HKObjectType.quantityType(forIdentifier: .distanceWalkingRunning) {
        values.insert(distance)
      }
      if let energy = HKObjectType.quantityType(forIdentifier: .activeEnergyBurned) {
        values.insert(energy)
      }
      return values
    }

    private func integer(
      _ call: DeviceCall, _ key: String, _ fallback: Int, _ range: ClosedRange<Int>
    ) -> Int {
      guard let value = call.arguments[key]?.intValue else { return fallback }
      return min(max(value, range.lowerBound), range.upperBound)
    }

    private func string(_ call: DeviceCall, _ key: String, _ fallback: String) -> String {
      call.arguments[key]?.stringValue ?? fallback
    }

    private func dateRange(days: Int) -> (start: Date, end: Date) {
      let calendar = Calendar.autoupdatingCurrent
      let end = Date()
      let startOfToday = calendar.startOfDay(for: end)
      return (calendar.date(byAdding: .day, value: -(days - 1), to: startOfToday)!, end)
    }

    private func activitySummary(days: Int) async throws -> JSONValue {
      let range = dateRange(days: days)
      let calendar = Calendar.autoupdatingCurrent
      let predicate = HKQuery.predicate(
        forActivitySummariesBetweenStart: calendar.dateComponents(
          [.era, .year, .month, .day], from: range.start),
        end: calendar.dateComponents([.era, .year, .month, .day], from: range.end))
      let summaries: [HKActivitySummary] = try await withCheckedThrowingContinuation {
        continuation in
        let query = HKActivitySummaryQuery(predicate: predicate) { _, values, error in
          if let error { continuation.resume(throwing: error) }
          else { continuation.resume(returning: values ?? []) }
        }
        store.execute(query)
      }
      let values = summaries.sorted { left, right in
        calendar.date(from: left.dateComponents(for: calendar)) ?? .distantPast
          < calendar.date(from: right.dateComponents(for: calendar)) ?? .distantPast
      }.map { summary -> JSONValue in
        let date = calendar.date(from: summary.dateComponents(for: calendar)) ?? range.start
        return .object([
          "date": .string(Self.dayFormatter.string(from: date)),
          "activeEnergyKcal": .number(
            summary.activeEnergyBurned.doubleValue(for: .kilocalorie())),
          "activeEnergyGoalKcal": .number(
            summary.activeEnergyBurnedGoal.doubleValue(for: .kilocalorie())),
          "exerciseMinutes": .number(
            summary.appleExerciseTime.doubleValue(for: .minute())),
          "exerciseGoalMinutes": .number(
            summary.appleExerciseTimeGoal.doubleValue(for: .minute())),
          "standHours": .number(summary.appleStandHours.doubleValue(for: .count())),
          "standGoalHours": .number(
            summary.appleStandHoursGoal.doubleValue(for: .count())),
        ])
      }
      return .object([
        "requestedDays": .number(Double(days)),
        "days": .array(values),
        "privacy": .string("Daily aggregates only; no route or sensor samples were read."),
      ])
    }

    private func workoutSummary(days: Int, activity: String, limit: Int) async throws
      -> JSONValue
    {
      let range = dateRange(days: days)
      let workouts = try await workouts(start: range.start, end: range.end, limit: limit)
        .filter { activity == "all" || Self.activityName($0.workoutActivityType) == activity }
        .prefix(limit)
      let values = workouts.map { workout -> JSONValue in
        .object([
          "activity": .string(Self.activityName(workout.workoutActivityType)),
          "start": .string(Self.timestampFormatter.string(from: workout.startDate)),
          "end": .string(Self.timestampFormatter.string(from: workout.endDate)),
          "durationMinutes": .number(workout.duration / 60),
          "distanceKilometers": workout.totalDistance.map {
            .number($0.doubleValue(for: .meterUnit(with: .kilo)))
          } ?? .null,
          "activeEnergyKcal": workout.totalEnergyBurned.map {
            .number($0.doubleValue(for: .kilocalorie()))
          } ?? .null,
        ])
      }
      return .object([
        "requestedDays": .number(Double(days)),
        "activity": .string(activity),
        "workouts": .array(Array(values)),
        "privacy": .string("Workout summaries only; no routes or sensor samples were read."),
      ])
    }

    private func runningTotals(days: Int) async throws -> JSONValue {
      let range = dateRange(days: days)
      let runs = try await workouts(start: range.start, end: range.end, limit: 500)
        .filter { $0.workoutActivityType == .running }
      let calendar = Calendar.autoupdatingCurrent
      var weeks: [Date: (count: Int, distance: Double, duration: Double)] = [:]
      for workout in runs {
        let start = calendar.dateInterval(of: .weekOfYear, for: workout.startDate)?.start
          ?? calendar.startOfDay(for: workout.startDate)
        var value = weeks[start] ?? (0, 0, 0)
        value.count += 1
        value.distance += workout.totalDistance?.doubleValue(
          for: .meterUnit(with: .kilo)) ?? 0
        value.duration += workout.duration / 60
        weeks[start] = value
      }
      let weekly: [JSONValue] = weeks.keys.sorted().map { start in
        let value = weeks[start]!
        return .object([
          "weekStarting": .string(Self.dayFormatter.string(from: start)),
          "runs": .number(Double(value.count)),
          "distanceKilometers": .number(value.distance),
          "durationMinutes": .number(value.duration),
        ])
      }
      let totalDistance = runs.reduce(0) {
        $0 + ($1.totalDistance?.doubleValue(for: .meterUnit(with: .kilo)) ?? 0)
      }
      return .object([
        "requestedDays": .number(Double(days)),
        "runCount": .number(Double(runs.count)),
        "distanceKilometers": .number(totalDistance),
        "durationMinutes": .number(runs.reduce(0) { $0 + $1.duration / 60 }),
        "weeks": .array(weekly),
        "privacy": .string("Aggregated running workouts only; no routes or sensor samples were read."),
      ])
    }

    private func stepSummary(days: Int) async throws -> JSONValue {
      guard let type = HKObjectType.quantityType(forIdentifier: .stepCount) else {
        throw HealthError.unavailable
      }
      let range = dateRange(days: days)
      var interval = DateComponents()
      interval.day = 1
      let collection: HKStatisticsCollection = try await withCheckedThrowingContinuation {
        continuation in
        let query = HKStatisticsCollectionQuery(
          quantityType: type,
          quantitySamplePredicate: HKQuery.predicateForSamples(
            withStart: range.start, end: range.end),
          options: .cumulativeSum,
          anchorDate: Calendar.autoupdatingCurrent.startOfDay(for: range.start),
          intervalComponents: interval)
        query.initialResultsHandler = { _, value, error in
          if let error { continuation.resume(throwing: error) }
          else if let value { continuation.resume(returning: value) }
          else { continuation.resume(throwing: HealthError.unavailable) }
        }
        store.execute(query)
      }
      var values: [JSONValue] = []
      collection.enumerateStatistics(from: range.start, to: range.end) { statistics, _ in
        let quantity = statistics.sumQuantity()
        values.append(.object([
          "date": .string(Self.dayFormatter.string(from: statistics.startDate)),
          "steps": quantity.map { .number($0.doubleValue(for: .count())) } ?? .null,
          "hasData": .bool(quantity != nil),
        ]))
      }
      return .object([
        "requestedDays": .number(Double(days)),
        "days": .array(values),
        "privacy": .string("Daily step aggregates only; no individual samples were read."),
      ])
    }

    private func workouts(start: Date, end: Date, limit: Int) async throws -> [HKWorkout] {
      try await withCheckedThrowingContinuation { continuation in
        let query = HKSampleQuery(
          sampleType: HKObjectType.workoutType(),
          predicate: HKQuery.predicateForSamples(withStart: start, end: end),
          limit: limit,
          sortDescriptors: [NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)]
        ) { _, samples, error in
          if let error { continuation.resume(throwing: error) }
          else { continuation.resume(returning: samples as? [HKWorkout] ?? []) }
        }
        store.execute(query)
      }
    }

    private static func activityName(_ value: HKWorkoutActivityType) -> String {
      switch value {
      case .running: "running"
      case .walking: "walking"
      case .cycling: "cycling"
      case .swimming: "swimming"
      default: "other"
      }
    }

    private static let dayFormatter: DateFormatter = {
      let value = DateFormatter()
      value.calendar = Calendar(identifier: .iso8601)
      value.locale = Locale(identifier: "en_US_POSIX")
      value.dateFormat = "yyyy-MM-dd"
      return value
    }()
    private static let timestampFormatter = ISO8601DateFormatter()

    private enum HealthError: LocalizedError {
      case unavailable
      var errorDescription: String? { "The requested Health data is unavailable." }
    }
  }
#endif
