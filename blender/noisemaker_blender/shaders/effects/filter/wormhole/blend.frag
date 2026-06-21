#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
// Wormhole Blend
// Normalize accumulated scatter nm_buffer, sqrt, blend with original.
// Uses mean-based normalization (robust to sparse sampling) instead of
// min/max (which flickered due to missing outlier hotspots in the grid).

void main() {
    vec2 globalCoord = gl_FragCoord.xy + tileOffset;
    vec2 uv = globalCoord / fullResolution;

    vec4 src = nmTex(inputTex, gl_FragCoord.xy / vec2(textureSize(inputTex, 0)));
    vec4 accum = nmTex(accumTex, gl_FragCoord.xy / vec2(textureSize(accumTex, 0)));

    // Estimate mean of accum nm_buffer from 32x32 grid (1024 samples).
    // Mean is robust to sparse sampling unlike min/max.
    float sum = 0.0;
    float count = 0.0;
    for (int gy = 0; gy < 32; gy++) {
        for (int gx = 0; gx < 32; gx++) {
            vec2 sampleUV = (vec2(float(gx), float(gy)) + 0.5) / 32.0;
            vec4 s = nmTex(accumTex, sampleUV);
            float v = (s.r + s.g + s.b) / 3.0;
            sum += v;
            count += 1.0;
        }
    }
    float mean = sum / count;

    // Normalize: scale so that mean maps to ~0.25 (after sqrt -> ~0.5)
    // This gives a stable, well-distributed output range
    vec3 normalized;
    if (mean > 0.0) {
        normalized = clamp(accum.rgb / (mean * 4.0), 0.0, 1.0);
    } else {
        normalized = accum.rgb;
    }

    vec3 sqrtVal = sqrt(normalized);

    fragColor = vec4(mix(src.rgb, sqrtVal, alpha), src.a);
}
