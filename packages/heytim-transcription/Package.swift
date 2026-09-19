// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "HeyTimNemotron",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "HeyTimNemotron", targets: ["HeyTimNemotron"]),
        .executable(name: "heytim-nemotron-smoke", targets: ["HeyTimNemotronSmoke"]),
    ],
    targets: [
        .binaryTarget(
            name: "SherpaOnnxMacOS",
            path: "ios/Generated/Frameworks/macOS/sherpa-onnx.xcframework"
        ),
        .binaryTarget(
            name: "OnnxRuntimeMacOS",
            path: "ios/Generated/Frameworks/macOS/onnxruntime.xcframework"
        ),
        .binaryTarget(
            name: "SherpaOnnxIOS",
            path: "ios/Generated/Frameworks/iOS/sherpa-onnx.xcframework"
        ),
        .binaryTarget(
            name: "OnnxRuntimeIOS",
            path: "ios/Generated/Frameworks/iOS/onnxruntime.xcframework"
        ),
        .target(
            name: "HeyTimNemotron",
            dependencies: [
                .target(name: "SherpaOnnxMacOS", condition: .when(platforms: [.macOS])),
                .target(name: "OnnxRuntimeMacOS", condition: .when(platforms: [.macOS])),
                .target(name: "SherpaOnnxIOS", condition: .when(platforms: [.iOS])),
                .target(name: "OnnxRuntimeIOS", condition: .when(platforms: [.iOS])),
            ],
            path: "ios",
            exclude: [
                "Generated/Frameworks",
                "Generated/Notices",
                "Notices",
            ],
            sources: ["Core"],
            resources: [.copy("Generated/Models")],
            linkerSettings: [
                .linkedFramework("AVFoundation"),
                .linkedFramework("Accelerate"),
                .linkedFramework("CoreFoundation"),
                .linkedFramework("CoreML"),
                .linkedLibrary("c++"),
            ]
        ),
        .executableTarget(
            name: "HeyTimNemotronSmoke",
            dependencies: ["HeyTimNemotron"],
            path: "macos-smoke"
        ),
        .testTarget(
            name: "HeyTimNemotronTests",
            dependencies: ["HeyTimNemotron"],
            path: "Tests/HeyTimNemotronTests"
        ),
    ]
)
