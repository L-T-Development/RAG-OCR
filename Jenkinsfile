// Global Groovy map to hold the dynamic configuration determined in Stage 2.
// This is declared outside the 'pipeline' block so it is accessible across stages
// within the 'script' steps.
def globalConfig = [:]

pipeline {
    agent any

    // 1. SAFETY & MAINTENANCE OPTIONS
    options {
        timeout(time: 1, unit: 'HOURS')                    // Kill if runs too long
        buildDiscarder(logRotator(numToKeepStr: '10')) // Keep last 10 builds only
        disableConcurrentBuilds()                          // Prevent cache corruption
    }

    // 2. PARAMETERS (Manual Triggers)
    parameters {
        booleanParam(name: 'CLEAN_CACHE', defaultValue: false, description: 'Check to wipe Docker dependency caches (Force fresh download)')
    }

    environment {
        // DEFAULT FALLBACK VALUES - Used if no project type is detected
        PROJECT_TYPE = "unknown"
        CONTAINER_IMAGE = "alpine"
        WORK_DIR = "."
        CMD_LINT = "echo 'Skipping Lint'"
        CMD_TEST = "echo 'Skipping Test'"
        CMD_BUILD = "echo 'No build command'"
        ARTIFACT_PATTERN = "README.md"

        // Credentials
        SONAR_TOKEN = credentials('sonarqube-token')
    }

    stages {

        stage('1. Checkout & Preparation') {
            steps {
                // A. Handle Cache Cleaning Request
                script {
                    if (params.CLEAN_CACHE) {
                        echo "!!! CLEANING CACHE REQUESTED !!!"
                        // We use '|| true' so it doesn't fail if volumes don't exist yet
                        sh "docker volume rm maven-repo npm-cache pip-cache || true"
                        echo "✓ Cache volumes deleted."
                    }
                }

                // B. Checkout Code
               checkout scm
                // C. Secret Detection (Gitleaks)
                script {
                    echo "--- [SECURITY] Starting Secret Detection ---"
                    def gitleaksExit = sh(
                        script: "docker run --rm -v ${WORKSPACE}:/code zricethezav/gitleaks:latest detect --source /code --no-git --verbose",
                        returnStatus: true
                    )
                    if (gitleaksExit != 0) error "SECURITY BREACH: Secrets detected!"
                }

                // D. Vulnerability Scan (Trivy)
//                 script {
//                     echo "--- [SECURITY] Starting Vulnerability Scan ---"
//                     def trivyExit = sh(
//     script: "docker run --rm -v ${WORKSPACE}:/code aquasec/trivy:latest fs --timeout 15m --severity HIGH,CRITICAL --exit-code 1 /code",
//     returnStatus: true
// )
//                     if (trivyExit != 0) error "SECURITY BREACH: Critical vulnerabilities found!"
//                 }
            }
        }

       stage('2. Configure Pipeline') {
            steps {
                script {
                    // Initialize Map
                    globalConfig.putAll([
                        PROJECT_TYPE: env.PROJECT_TYPE,
                        IMAGE: env.CONTAINER_IMAGE,
                        WORK_DIR: env.WORK_DIR,
                        LINT: env.CMD_LINT,
                        TEST: env.CMD_TEST,
                        BUILD: env.CMD_BUILD,
                        ARTIFACT: env.ARTIFACT_PATTERN
                    ])

                    // STRATEGY 1: PIPELINE.YAML (Priority)
                    if (fileExists('pipeline.yaml')) {
                         echo "--- Found pipeline.yaml! Loading configuration... ---"
                         def config = readYaml file: 'pipeline.yaml'
                         globalConfig.put('PROJECT_TYPE', config.type)
                         globalConfig.put('IMAGE', config.image)
                         globalConfig.put('WORK_DIR', config.dir)
                         globalConfig.put('LINT', config.scripts.lint ?: env.CMD_LINT)
                         globalConfig.put('TEST', config.scripts.test ?: env.CMD_TEST)
                         globalConfig.put('BUILD', config.scripts.build)
                         globalConfig.put('ARTIFACT', config.artifact_pattern)
                    }
                    // STRATEGY 2: AUTO-DETECT (Fallback)
                    else {
                        echo "--- No config found. Running Auto-Detect... ---"
                        
                        if (fileExists('pom.xml')) {
                            echo "--- Detected: JAVA (Maven) ---"
                            globalConfig.put('PROJECT_TYPE', 'java')
                            globalConfig.put('IMAGE', 'maven:3.9.6-eclipse-temurin-17')
                            globalConfig.put('LINT', 'mvn checkstyle:check')
                            // Force 'verify' to ensure JaCoCo runs
                            globalConfig.put('TEST', 'mvn clean verify -DskipTests=false') 
                            globalConfig.put('BUILD', 'mvn clean package -DskipTests')
                            globalConfig.put('ARTIFACT', 'target/*.jar')
                        }
                        else if (fileExists('package.json')) {
                            echo "--- Detected: NODE.JS ---"
                            globalConfig.put('PROJECT_TYPE', 'node')
                            globalConfig.put('IMAGE', 'node:20-alpine')
                            globalConfig.put('LINT', 'npm run lint')
                            globalConfig.put('TEST', 'npm test')
                            globalConfig.put('BUILD', 'npm install && npm run build')
                            globalConfig.put('ARTIFACT', 'dist/')
                        }
                        else if (fileExists('requirements.txt')) {
                            echo "--- Detected: PYTHON ---"
                            globalConfig.put('PROJECT_TYPE', 'python')
                            globalConfig.put('IMAGE', 'python:3.10-slim')
                            
                            // Python needs explicit installs because the container starts empty
                            // We chain commands: Install -> Run
                            globalConfig.put('LINT', 'pip install pylint && pylint --fail-under=5.0 **/*.py')
                            globalConfig.put('TEST', 'pip install -r requirements.txt && pip install pytest pytest-cov && pytest --cov=.')
                            
                            // Python build usually means creating a Wheel/Distribution
                            globalConfig.put('BUILD', 'pip install build && python3 -m build')
                            globalConfig.put('ARTIFACT', 'dist/*')
                        }
                        else {
                            error "FATAL: Project type not recognized."
                        }
                    }
                }
            }
        }

  stage('3. Quality Gates (Lint -> Test -> Scan)') {
    steps {
        script {
            withEnv([
                "CONTAINER_IMAGE=${globalConfig.IMAGE}",
                "CMD_TEST=${globalConfig.TEST}",
                "CMD_LINT=${globalConfig.LINT}",
                "WORK_DIR=${globalConfig.WORK_DIR}"
            ]) {
                echo "--- Environment: ${env.CONTAINER_IMAGE} ---"

                // Docker arguments for all containers in this stage
                def dockerArgs = """
-v ${WORKSPACE}:/app \\
-v maven-repo:/root/.m2 \\
-v npm-cache:/root/.npm \\
-v pip-cache:/root/.cache/pip \\
-w /app/${env.WORK_DIR} \\
--add-host=host.docker.internal:host-gateway
""".trim()

                // STEP A: LINT (Uncommented when ready)
                echo '--- [GATE 1] Linting ---'
                sh """
                    docker run --rm ${dockerArgs} \
                    ${env.CONTAINER_IMAGE} \
                    /bin/sh -c '${env.CMD_LINT}'
                """.trim()

                // STEP B: TEST & COVERAGE
                echo '--- [GATE 2] Unit Tests & Coverage ---'
                sh """
                    docker run --rm ${dockerArgs} \
                    ${env.CONTAINER_IMAGE} \
                    /bin/sh -c '${env.CMD_TEST}'
                """.trim()

                // STEP C & D: SONARQUBE ANALYSIS AND QUALITY GATE
                // The 'withSonarQubeEnv' sets the environment for the Agent (Host OS),
                // then we override it for the Docker scan where necessary.
                
                withSonarQubeEnv('MyLocalSonarQube') {
                    echo '--- [GATE 3] Static Analysis ---'
                    
                    // Define the Sonar Host URL for use INSIDE the Docker containers
                    // This resolves the "Connection refused" error.
                    def DOCKER_SONAR_URL = 'http://host.docker.internal:9001'
                    
                    if (globalConfig.PROJECT_TYPE == 'java') {
                        sh """
                            docker run --rm ${dockerArgs} \
                            -e SONAR_HOST_URL=${DOCKER_SONAR_URL} \
                            -e SONAR_TOKEN=${env.SONAR_AUTH_TOKEN} \
                            ${env.CONTAINER_IMAGE} \
                            /bin/sh -c '
                                mvn sonar:sonar \
                                -Dsonar.projectKey=${env.JOB_NAME} \
                                -Dsonar.coverage.jacoco.xmlReportPaths=target/site/jacoco/jacoco.xml
                            '
                        """.trim()
                    } else if (globalConfig.PROJECT_TYPE == 'node') {
                        sh """
                            docker run --rm ${dockerArgs} \
                            -e SONAR_HOST_URL=${DOCKER_SONAR_URL} \
                            -e SONAR_TOKEN=${env.SONAR_AUTH_TOKEN} \
                            sonarsource/sonar-scanner-cli \
                            -Dsonar.projectKey=${env.JOB_NAME} \
                            -Dsonar.sources=. \
                            -Dsonar.javascript.lcov.reportPaths=coverage/lcov.info
                        """.trim()
                    } else if (globalConfig.PROJECT_TYPE == 'python') {
                        sh """
                            docker run --rm ${dockerArgs} \
                            -e SONAR_HOST_URL=${DOCKER_SONAR_URL} \
                            -e SONAR_TOKEN=${env.SONAR_AUTH_TOKEN} \
                            sonarsource/sonar-scanner-cli \
                            -Dsonar.projectKey=${env.JOB_NAME} \
                            -Dsonar.sources=. \
                            -Dsonar.python.coverage.reportPaths=coverage.xml
                        """.trim()
                    }
                    
                
                }
                // STEP D: ENFORCE QUALITY GATE
                    // echo "--- Waiting for Quality Gate Result ---"
                    // // This uses the configuration's URL (http://localhost:9001), which the Agent can resolve.
                    // timeout(time: 5, unit: 'MINUTES') {
                    //     waitForQualityGate abortPipeline: true
                    // }
            }
        }
    }
} 

        stage('4. Build Artifact') {
            when {
                branch 'main'  // Only build final artifact on main
            }
            steps {
                script {
                    withEnv([
                        "CONTAINER_IMAGE=${globalConfig.IMAGE}",
                        "CMD_BUILD=${globalConfig.BUILD}",
                        "WORK_DIR=${globalConfig.WORK_DIR}" // Use WORK_DIR from globalConfig
                    ]) {
                        echo "--- Running Build Command: ${env.CMD_BUILD} ---"

                        // Cleaned up indentation for robust use with .trim()
                        def dockerArgs = """
-v ${WORKSPACE}:/app \\
-v maven-repo:/root/.m2 \\
-v npm-cache:/root/.npm \\
-v pip-cache:/root/.cache/pip \\
-w /app/${env.WORK_DIR}
""".trim()

                        sh "docker run --rm ${dockerArgs} ${env.CONTAINER_IMAGE} /bin/sh -c '${env.CMD_BUILD}'"
                    }
                }
            }
        }

        stage('5. Archive & Deliver') {
            when {
                branch 'main'  // Only archive on main branch
            }
            steps {
                withEnv(["ARTIFACT_PATTERN=${globalConfig.ARTIFACT}"]) {
                    echo "--- Archiving Production Artifact for Offline Delivery ---"
                    archiveArtifacts artifacts: "${env.ARTIFACT_PATTERN}", allowEmptyArchive: false
                }
            }
        }
    } // End of stages
} // End of pipeline