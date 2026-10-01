#if os(iOS)
  import Foundation
  import HealthKit
  import Observation

  @MainActor @Observable
  final class AppleHealthCoordinator {
    struct LocalOverview {
      let stepCount: Int?
      let stepDays: Int
      let workoutCount: Int
      let runningCount: Int
      let runningKilometers: Double
    }
    static let permissionRequestedKey = "heytim.apple-health.permission-requested"

    private let store = HKHealthStore()
    private(set) var permissionRequested = UserDefaults.standard.bool(
      forKey: permissionRequestedKey)
    private(set) var errorMessage: String?

    var isAvailable: Bool { HKHealthStore.isHealthDataAvailable() }

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

    func localOverview() async -> LocalOverview? {
      guard await requestReadAccess() else { return nil }
      do {
        let steps = try await stepSummary(days: 7).objectValue?["days"]
        let stepDays = steps?.arrayValue ?? []
        let recordedSteps = stepDays.compactMap {
          $0.objectValue?["steps"]?.numberValue
        }
        let workouts = try await workouts(
          start: dateRange(days: 90).start, end: Date())
        let running = workouts.filter { $0.workoutActivityType == .running }
        let recentWorkouts = workouts.filter { $0.startDate >= dateRange(days: 30).start }
        errorMessage = nil
        return LocalOverview(
          stepCount: recordedSteps.isEmpty ? nil : Int(recordedSteps.reduce(0, +)),
          stepDays: recordedSteps.count,
          workoutCount: recentWorkouts.count,
          runningCount: running.count,
          runningKilometers: running.reduce(0) {
            $0 + ($1.totalDistance?.doubleValue(for: .meterUnit(with: .kilo)) ?? 0)
          })
      } catch {
        errorMessage = error.localizedDescription
        return nil
      }
    }

    private static var readTypes: Set<HKObjectType> {
      var values: Set<HKObjectType> = [HKObjectType.workoutType()]
      if let steps = HKObjectType.quantityType(forIdentifier: .stepCount) {
        values.insert(steps)
      }
      return values
    }

    private func dateRange(days: Int) -> (start: Date, end: Date) {
      let calendar = Calendar.autoupdatingCurrent
      let end = Date()
      let startOfToday = calendar.startOfDay(for: end)
      return (calendar.date(byAdding: .day, value: -(days - 1), to: startOfToday)!, end)
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

    private func workouts(start: Date, end: Date) async throws -> [HKWorkout] {
      try await withCheckedThrowingContinuation { continuation in
        let query = HKSampleQuery(
          sampleType: HKObjectType.workoutType(),
          predicate: HKQuery.predicateForSamples(withStart: start, end: end),
          limit: HKObjectQueryNoLimit,
          sortDescriptors: [NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: false)]
        ) { _, samples, error in
          if let error { continuation.resume(throwing: error) }
          else { continuation.resume(returning: samples as? [HKWorkout] ?? []) }
        }
        store.execute(query)
      }
    }

    private static let dayFormatter: DateFormatter = {
      let value = DateFormatter()
      value.calendar = Calendar(identifier: .iso8601)
      value.locale = Locale(identifier: "en_US_POSIX")
      value.dateFormat = "yyyy-MM-dd"
      return value
    }()
    private enum HealthError: LocalizedError {
      case unavailable
      var errorDescription: String? { "The requested Health data is unavailable." }
    }
  }
#endif
