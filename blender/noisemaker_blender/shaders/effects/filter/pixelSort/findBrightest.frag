#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
// GPGPU Pass 2: Find brightest pixel x-coordinate per row (optimized)
// Input: luminance nmTex(R = luminance)
// Output: R = brightest x (normalized), G = max luminance, B = 0, A = 1
// Uses sparse sampling for O(1) approximate result

void main() {
    ivec2 coord = ivec2(gl_FragCoord.xy);
    ivec2 size = textureSize(lumTex, 0);
    int y = coord.y;
    int width = size.x;
    
    // Use sparse sampling to find approximate brightest pixel
    const int NUM_SAMPLES = 32;
    float maxLum = -1.0;
    int brightestX = 0;
    
    for (int s = 0; s < NUM_SAMPLES; s++) {
        int sampleX = (s * width) / NUM_SAMPLES;
        float lum = texelFetch(lumTex, ivec2(sampleX, y), 0).r;
        if (lum > maxLum) {
            maxLum = lum;
            brightestX = sampleX;
        }
    }
    
    // Output: normalized brightest x, max luminance
    fragColor = vec4(float(brightestX) / float(width - 1), maxLum, 0.0, 1.0);
}
