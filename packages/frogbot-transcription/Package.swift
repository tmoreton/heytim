// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "FroggyBotNemotron",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "FroggyBotNemotron", targets: ["FroggyBotNemotron"]),
        .executable(name: "frogbot-nemotron-smoke", targets: ["FroggyBotNemotronSmoke"]),
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
        .target(
            name: "FroggyBotNemotron",
            dependencies: ["SherpaOnnxMacOS", "OnnxRuntimeMacOS"],
            path: "ios",
            exclude: [
                "Expo",
                "FroggyBotTranscription.podspec",
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
            name: "FroggyBotNemotronSmoke",
            dependencies: ["FroggyBotNemotron"],
            path: "macos-smoke"
        ),
        .testTarget(
            name: "FroggyBotNemotronTests",
            dependencies: ["FroggyBotNemotron"],
            path: "Tests/FroggyBotNemotronTests"
        ),
    ]
)
