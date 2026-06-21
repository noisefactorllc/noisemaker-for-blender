/*
 * Motion Blur - Simple frame blending shader.
 * Mixes current input with previous frame for a motion blur effect.
 * Amount 0-100 maps to mix factor (stronger at higher values).
 */

void main() {
    vec2 uv = gl_FragCoord.xy / resolution;
    
    // If resetState is true, bypass feedback and return input directly
    if (resetState) {
        fragColor = texture(inputTex, uv);
        return;
    }

    vec4 current = texture(inputTex, uv);
    vec4 previous = texture(selfTex, uv);
    
    // Map amount 0-100 to 0-0.8 (clamped)
    float mixFactor = clamp(amount * 0.008, 0.0, 0.98);
    
    fragColor = mix(current, previous, mixFactor);
}
