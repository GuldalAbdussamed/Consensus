import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

let scene, camera, renderer, mixer, clock;
let currentAction;
const actions = {};

// Test Modeli: RobotExpressive (İçinde Wave, Dance, vb. animasyonlar var)
const MODEL_URL = 'https://raw.githubusercontent.com/mrdoob/three.js/master/examples/models/gltf/RobotExpressive/RobotExpressive.glb';

init();
animate();

function init() {
    const container = document.getElementById('canvas-container');

    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a1a);
    scene.fog = new THREE.Fog(0x1a1a1a, 10, 50);

    clock = new THREE.Clock();

    // Camera
    camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.25, 100);
    camera.position.set(-5, 3, 10);

    // Lights
    const hemiLight = new THREE.HemisphereLight(0xffffff, 0x444444, 2);
    hemiLight.position.set(0, 20, 0);
    scene.add(hemiLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.5);
    dirLight.position.set(0, 20, 10);
    dirLight.castShadow = true;
    scene.add(dirLight);

    // Ground
    const mesh = new THREE.Mesh(
        new THREE.PlaneGeometry(100, 100),
        new THREE.MeshPhongMaterial({ color: 0x222222, depthWrite: false })
    );
    mesh.rotation.x = -Math.PI / 2;
    mesh.receiveShadow = true;
    scene.add(mesh);

    // Grid
    const grid = new THREE.GridHelper(100, 40, 0x000000, 0x000000);
    grid.material.opacity = 0.2;
    grid.material.transparent = true;
    scene.add(grid);

    // Load Model
    const loader = new GLTFLoader();
    loader.load(MODEL_URL, function (gltf) {
        const model = gltf.scene;
        model.position.y = 0;
        scene.add(model);

        model.traverse(function (object) {
            if (object.isMesh) object.castShadow = true;
        });

        // Animations
        mixer = new THREE.AnimationMixer(model);

        const states = ['Idle', 'Walking', 'Running', 'Dance', 'Death', 'Sitting', 'Standing'];
        const emotes = ['Jump', 'Yes', 'No', 'Wave', 'Punch', 'ThumbsUp'];

        // Tüm animasyonları kaydet
        for (let i = 0; i < gltf.animations.length; i++) {
            const clip = gltf.animations[i];
            const action = mixer.clipAction(clip);
            actions[clip.name] = action;
            
            // Eğer emote ise bir kere oynasın
            if (emotes.indexOf(clip.name) >= 0) {
                action.clampWhenFinished = true;
                action.loop = THREE.LoopOnce;
            }
        }

        // Başlangıçta Idle oynat
        if (actions['Idle']) {
            currentAction = actions['Idle'];
            currentAction.play();
        }

        document.getElementById('status').innerText = "Model Yüklendi. Test Edebilirsiniz.";
        console.log("Kullanılabilir Animasyonlar:", Object.keys(actions));

    }, undefined, function (e) {
        console.error(e);
        document.getElementById('status').innerText = "Model Yüklenirken Hata Oluştu!";
    });

    // Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.shadowMap.enabled = true;
    container.appendChild(renderer.domElement);

    // Controls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 2, 0);
    controls.update();

    window.addEventListener('resize', onWindowResize);
}

// Oynat Butonu Logic
document.getElementById('play-btn').addEventListener('click', () => {
    const text = document.getElementById('gloss-input').value.trim().toUpperCase();
    if (!text) return;

    playGloss(text);
});

// Metin gelince ne oynayacak (Sözlük)
function playGloss(text) {
    if (!mixer) return;

    let targetAnim = "Idle";
    
    // Basit bir kelime->animasyon sözlüğü
    if (text === "MERHABA") targetAnim = "Wave";
    else if (text === "EVET") targetAnim = "Yes";
    else if (text === "HAYIR") targetAnim = "No";
    else if (text === "TAMAM") targetAnim = "ThumbsUp";
    else if (text === "ZIPLA") targetAnim = "Jump";
    else targetAnim = "Dance"; // Bilinmeyen kelimede dans etsin :)

    document.getElementById('status').innerText = `Oynatılıyor: ${targetAnim} (Metin: ${text})`;
    fadeToAction(targetAnim, 0.2);
}

function fadeToAction(name, duration) {
    if (!actions[name]) return;
    
    const previousAction = currentAction;
    currentAction = actions[name];

    if (previousAction !== currentAction) {
        previousAction.fadeOut(duration);
    }

    currentAction.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).fadeIn(duration).play();

    // Animasyon bitince tekrar Idle'a dön (Eğer loop once ise)
    mixer.addEventListener('finished', restoreState);
}

function restoreState() {
    mixer.removeEventListener('finished', restoreState);
    fadeToAction('Idle', 0.2);
}

function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
}

function animate() {
    requestAnimationFrame(animate);
    const dt = clock.getDelta();
    if (mixer) mixer.update(dt);
    renderer.render(scene, camera);
}
