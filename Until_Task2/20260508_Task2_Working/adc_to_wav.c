#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>

#define CHANNELS 1
#define BITS_PER_SAMPLE 16
#define ADC_MAX 4095

void write_le16(FILE *file, uint16_t value)
{
    fputc(value & 0xFF, file);
    fputc((value >> 8) & 0xFF, file);
}

void write_le32(FILE *file, uint32_t value)
{
    fputc(value & 0xFF, file);
    fputc((value >> 8) & 0xFF, file);
    fputc((value >> 16) & 0xFF, file);
    fputc((value >> 24) & 0xFF, file);
}

int16_t adc_to_pcm16(uint16_t adc_value)
{
    if (adc_value > ADC_MAX)
    {
        adc_value = ADC_MAX;
    }

    int32_t pcm = ((int32_t)adc_value * 65535 / ADC_MAX) - 32768;

    if (pcm > 32767)
    {
        pcm = 32767;
    }
    if (pcm < -32768)
    {
        pcm = -32768;
    }

    return (int16_t)pcm;
}

int main(int argc, char *argv[])
{
    printf("Program started\n");
    fflush(stdout);

    if (argc != 4)
    {
        printf("Usage: adc_to_wav input.data output.wav sample_rate\n");
        fflush(stdout);
        return 1;
    }

    const char *input_filename = argv[1];
    const char *output_filename = argv[2];
    uint32_t sample_rate = (uint32_t)atoi(argv[3]);

    printf("Input: %s\n", input_filename);
    printf("Output: %s\n", output_filename);
    printf("Sample rate: %u\n", sample_rate);
    fflush(stdout);

    FILE *input = fopen(input_filename, "rb");
    if (input == NULL)
    {
        printf("Error opening input file.\n");
        fflush(stdout);
        return 1;
    }

    FILE *output = fopen(output_filename, "wb");
    if (output == NULL)
    {
        printf("Error opening output file.\n");
        fflush(stdout);
        fclose(input);
        return 1;
    }

    printf("Files opened\n");
    fflush(stdout);

    fseek(input, 0, SEEK_END);
    long input_size_long = ftell(input);
    rewind(input);

    if (input_size_long <= 0)
    {
        printf("Input file is empty or invalid.\n");
        fflush(stdout);
        fclose(input);
        fclose(output);
        return 1;
    }

    uint32_t input_size = (uint32_t)input_size_long;
    uint32_t num_samples = input_size / 2;
    uint32_t data_chunk_size = num_samples * 2;
    uint32_t riff_chunk_size = 36 + data_chunk_size;

    printf("Input size: %u bytes\n", input_size);
    printf("Samples: %u\n", num_samples);
    fflush(stdout);

    uint32_t byte_rate = sample_rate * CHANNELS * BITS_PER_SAMPLE / 8;
    uint16_t block_align = CHANNELS * BITS_PER_SAMPLE / 8;

    fwrite("RIFF", 1, 4, output);
    write_le32(output, riff_chunk_size);
    fwrite("WAVE", 1, 4, output);

    fwrite("fmt ", 1, 4, output);
    write_le32(output, 16);
    write_le16(output, 1);
    write_le16(output, CHANNELS);
    write_le32(output, sample_rate);
    write_le32(output, byte_rate);
    write_le16(output, block_align);
    write_le16(output, BITS_PER_SAMPLE);

    fwrite("data", 1, 4, output);
    write_le32(output, data_chunk_size);

    printf("Header written\n");
    fflush(stdout);

    uint8_t buffer[2];

    for (uint32_t i = 0; i < num_samples; i++)
    {
        if (fread(buffer, 1, 2, input) != 2)
        {
            printf("Read stopped at sample %u\n", i);
            fflush(stdout);
            break;
        }

        uint16_t adc_value = buffer[0] | ((uint16_t)buffer[1] << 8);
        int16_t pcm_value = adc_to_pcm16(adc_value);

        write_le16(output, (uint16_t)pcm_value);
    }

    printf("Samples converted\n");
    fflush(stdout);

    fclose(input);
    fclose(output);

    printf("Done\n");
    fflush(stdout);

    return 0;
}