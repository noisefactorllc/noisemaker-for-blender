// Clear pass - fill with background color (premultiplied alpha)

void main() {
    fragColor = vec4(bgColor * bgAlpha, bgAlpha);
}
