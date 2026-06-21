uniform float audioSpectrum[128];

void main() {
    vec2 globalCoord = gl_FragCoord.xy + tileOffset;
    vec2 uv = globalCoord / fullResolution;

    // Sample the spectrum at this x position
    float fIndex = uv.x * 127.0;
    int i0 = int(floor(fIndex));
    int i1 = min(i0 + 1, 127);
    float fract_i = fract(fIndex);

    // Linearly interpolate between adjacent bins
    float s0 = audioSpectrum[i0];
    float s1 = audioSpectrum[i1];
    float mag = mix(s0, s1, fract_i) * gain;

    // Distance from nm_fragment to spectrum curve, in pixels
    float dist = abs(uv.y - mag) * fullResolution.y;

    // Anti-aliased line
    float line = smoothstep(lineThickness + 1.0, lineThickness, dist);

    // Fill below the curve
    float fill = smoothstep(mag + 1.0 / fullResolution.y, mag, uv.y) * 0.15;

    float alpha = max(line, fill);
    fragColor = vec4(lineColor * alpha, alpha);
}
