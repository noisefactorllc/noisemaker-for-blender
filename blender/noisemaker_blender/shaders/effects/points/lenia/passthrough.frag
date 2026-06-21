// Passthrough shader - copy input to output for 2D chain continuity

void main() {
    ivec2 coord = ivec2(gl_FragCoord.xy);
    fragColor = texelFetch(inputTex, coord, 0);
}
