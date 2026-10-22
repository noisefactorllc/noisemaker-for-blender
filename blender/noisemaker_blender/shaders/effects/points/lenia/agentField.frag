#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
// Agent update pass - samples pre-convolved U field
// Much faster than O(n²) as field is already computed

// Growth parameters

// Repulsion parameters

// Motion parameters

// MRT outputs

const float EPSILON = 0.0001;

// Growth function G(u) = exp(-((u - μ) / σ)²)
float growth(float u, float mu, float sigma) {
    float x = (u - mu) / sigma;
    return exp(-x * x);
}

// Derivative of growth: dG/du = G(u) * (-2(u-μ)/σ²)
float growthDerivative(float u, float mu, float sigma) {
    float G = growth(u, mu, sigma);
    return G * (-2.0 * (u - mu)) / (sigma * sigma);
}

void main() {
    ivec2 stateSize = textureSize(xyzTex, 0);
    ivec2 coord = ivec2(gl_FragCoord.xy);

    // Read current particle state
    vec4 xyz = texelFetch(xyzTex, coord, 0);
    vec4 vel = texelFetch(velTex, coord, 0);
    vec4 rgba = texelFetch(rgbaTex, coord, 0);

    float alive = xyz.w;

    // Pass through dead particles
    if (alive < 0.5) {
        outXYZ = xyz;
        outVel = vel;
        outRGBA = rgba;
        return;
    }

    // Sample U field at particle position
    vec2 uv = xyz.xy;
    float U = nmTex(fieldTex, uv).r;

    // Compute gradient of U via finite differences
    // Use the field texture's actual size for correct texel stepping
    vec2 fieldSize = vec2(textureSize(fieldTex, 0));
    vec2 texelSize = 1.0 / fieldSize;
    float Ux_plus = nmTex(fieldTex, fract(uv + vec2(texelSize.x, 0.0))).r;
    float Ux_minus = nmTex(fieldTex, fract(uv - vec2(texelSize.x, 0.0))).r;
    float Uy_plus = nmTex(fieldTex, fract(uv + vec2(0.0, texelSize.y))).r;
    float Uy_minus = nmTex(fieldTex, fract(uv - vec2(0.0, texelSize.y))).r;

    vec2 gradU = vec2(
        (Ux_plus - Ux_minus) / (2.0 * texelSize.x),
        (Uy_plus - Uy_minus) / (2.0 * texelSize.y)
    );

    // Scale gradient to world space
    float worldScale = min(resolution.x, resolution.y) * 0.05;
    gradU /= worldScale;

    // Compute growth gradient: ∇G = dG/dU * ∇U
    float dGdU = growthDerivative(U, muG, sigmaG);
    vec2 gradG = dGdU * gradU;

    // Repulsion gradient (from U field - areas of high density repel)
    // We approximate ∇R ≈ repulsion * ∇U for simplicity
    vec2 gradR = repulsion * gradU;

    // Total force: dp/dt = ∇G - ∇R
    vec2 force = gradG - gradR;

    // Limit force magnitude for stability
    float forceMag = length(force);
    if (forceMag > 10.0) {
        force = force / forceMag * 10.0;
    }

    // Update position (Euler integration)
    vec2 newPos = uv + force * dt * 0.01;

    // Wrap to [0,1] bounds (toroidal topology)
    newPos = fract(newPos + 1.0);

    // Store velocity for visualization
    vec2 velocity = force * dt * 0.01;

    // Update age
    float age = vel.z + 0.016;

    // Output
    outXYZ = vec4(newPos, xyz.z, 1.0);  // Keep z, stay alive
    outVel = vec4(velocity, age, vel.w);  // Store velocity, age, seed
    outRGBA = rgba;  // Color unchanged
}
