// Diffuse Pass - Decay existing trail

void main() {
    vec2 uv = gl_FragCoord.xy / resolution;
    
    // Sample the trail texture directly (no blur)
    vec4 trailColor = texture(trailTex, uv);
    
    // Apply intensity decay (persistence)
    // intensity=100 means no decay, intensity=0 means instant fade
    float decay = clamp(intensity / 100.0, 0.0, 1.0);
    fragColor = trailColor * decay;
}
